"""Business logic for the Document Upload module (UML Phase 3).

Stores the raw file in object storage (S3, local-disk fallback - see
app/core/storage.py), then runs it through DocumentProcessingService
(extract -> chunk -> embed -> store) so it becomes searchable via RAG
(app/services/vector_search_service.py). Processing failures don't fail the
upload itself - the file is already safely stored; the upload's `status`
records whether indexing succeeded so callers/UI can show it.

Zip archives (upload_zip_archive) are extracted in memory and every member
with an allowed extension is run through the exact same store+process path
as a single-file upload, one AssessmentUpload row per member - there is no
special "archive" record, the zip itself is never stored.
"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
import os
import zipfile
from typing import Any, AsyncGenerator, Dict, List, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core import observability
from app.core.config import settings
from app.core.exceptions import BadRequestException, ResourceNotFoundException
from app.core.storage import ObjectStorage, make_upload_key
from app.entities.assessment import Assessment
from app.entities.upload import AssessmentUpload
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.upload_repository import UploadRepository
from app.services.document_processing_service import DocumentProcessingService

logger = logging.getLogger("emios")

# Matches what DocumentProcessingService.extract_text() actually knows how to parse
# (app/services/document_processing_service.py) plus the plain-text formats it falls
# back to - anything else is rejected up front rather than silently mis-decoded.
# Shared by the single-file route and zip-member filtering (app/api/v1/uploads.py).
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".json", ".txt", ".md"}

# Zip entries that are never real documents - macOS's resource-fork sidecar
# folder and per-directory Finder metadata files.
_ZIP_IGNORED_PREFIXES = ("__MACOSX/",)
_ZIP_IGNORED_NAMES = {".ds_store"}

# How many zip members upload_zip_archive_stream() stores+indexes at once.
# Each member's own embedding calls are separately capped by
# document_processing_service's process-wide _embed_semaphore, so raising
# this mostly buys parallelism on the S3 write / text extraction / DB write
# steps rather than opening the floodgates on Bedrock traffic.
_MAX_CONCURRENT_ZIP_MEMBERS = 5


class UploadService:
    def __init__(
        self,
        upload_repo: UploadRepository,
        assessment_repo: AssessmentRepository,
        chunk_repo: DocumentChunkRepository,
    ):
        self.upload_repo = upload_repo
        self.assessment_repo = assessment_repo
        self.chunk_repo = chunk_repo
        self.document_processor = DocumentProcessingService(chunk_repo)
        self.storage = ObjectStorage()

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def ensure_assessment_exists(self, assessment_id: str) -> None:
        """Raises ResourceNotFoundException if `assessment_id` doesn't exist.
        Called eagerly by the streaming zip-upload route, before the
        StreamingResponse is constructed - mirrors DiscoveryService.
        ensure_ready_for_discovery()'s documented reasoning exactly: once a
        StreamingResponse starts, its 200 status/headers are already sent to
        the client, so an exception raised later inside the generator (e.g.
        upload_zip_archive_stream()'s own _require_assessment call) can no
        longer become a normal 404 JSON body - it just aborts the connection
        with an empty stream, silently, with nothing for the caller's error
        handling to catch. Checking here first avoids ever hitting that path
        for the single most common failure mode (a stale/typo'd assessment_id)."""
        await self._require_assessment(assessment_id)

    async def upload_document(
        self,
        assessment_id: str,
        filename: str,
        content_type: str,
        source_type: str,
        file_bytes: bytes,
    ) -> Tuple[AssessmentUpload, int]:
        """Stores + indexes one document. Returns (upload, chunk_count)."""
        await self._require_assessment(assessment_id)
        return await self._store_and_process(assessment_id, filename, content_type, source_type, file_bytes)

    async def upload_zip_archive(
        self,
        assessment_id: str,
        content_type: str,
        source_type: str,
        file_bytes: bytes,
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        """Non-streaming entry point: drains upload_zip_archive_stream() and
        returns its terminal event's payload - mirrors DiscoveryService's
        run_discovery()/run_discovery_stream() split. `uploads` entries are
        plain dicts matching UploadResponse's fields (see app/api/v1/uploads.py),
        not AssessmentUpload entities - members are now stored+indexed
        concurrently, each through its own short-lived DB session (see
        _store_and_process_isolated), so there's no single request-scoped
        session left to hand back a live ORM object bound to."""
        uploads: List[Dict[str, Any]] = []
        skipped: List[Tuple[str, str]] = []
        async for event in self.upload_zip_archive_stream(assessment_id, content_type, source_type, file_bytes):
            if event["type"] == "error":
                raise BadRequestException(event["message"])
            if event["type"] == "complete":
                uploads = event["uploads"]
                skipped = [(s["filename"], s["reason"]) for s in event["skipped"]]
        return uploads, skipped

    async def upload_zip_archive_stream(
        self,
        assessment_id: str,
        content_type: str,
        source_type: str,
        file_bytes: bytes,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Extracts a zip archive in memory and stores + indexes every member
        with an allowed extension, streamed as progress events. Members are
        processed concurrently (bounded by _MAX_CONCURRENT_ZIP_MEMBERS) rather
        than one at a time - each one's index step makes a real
        embedding-model call, so a multi-file archive processed sequentially
        is inherently slow (a 48-file archive can take 7+ minutes end to end).
        The archive itself is never stored - only its extracted members
        become AssessmentUpload rows. Event `type`s: start, member_start,
        member_result, member_skipped, complete, error.
        """
        await self._require_assessment(assessment_id)
        logger.info(f"Zip upload started for assessment '{assessment_id}': {len(file_bytes)} bytes.")

        buffer = io.BytesIO(file_bytes)
        if not zipfile.is_zipfile(buffer):
            logger.warning(f"Zip upload for assessment '{assessment_id}' rejected: not a valid zip archive.")
            yield {"type": "error", "message": "The uploaded file is not a valid zip archive."}
            return

        try:
            skipped: List[Tuple[str, str]] = []
            # (index, base_name, member_bytes, member_content_type) for every
            # member that passed the skip checks below.
            to_process: List[Tuple[int, str, bytes, str]] = []

            with zipfile.ZipFile(buffer) as archive:
                members = [info for info in archive.infolist() if not info.is_dir()]

                if len(members) > settings.MAX_ZIP_MEMBERS:
                    logger.warning(
                        f"Zip upload for assessment '{assessment_id}' rejected: {len(members)} members "
                        f"exceeds the {settings.MAX_ZIP_MEMBERS}-file limit."
                    )
                    yield {
                        "type": "error",
                        "message": (
                            f"Archive contains {len(members)} files, exceeding the "
                            f"{settings.MAX_ZIP_MEMBERS}-file limit per upload."
                        ),
                    }
                    return

                total_uncompressed = sum(info.file_size for info in members)
                if total_uncompressed > settings.MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                    max_mb = settings.MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES // (1024 * 1024)
                    logger.warning(
                        f"Zip upload for assessment '{assessment_id}' rejected: {total_uncompressed} "
                        f"uncompressed bytes exceeds the {max_mb}MB limit."
                    )
                    yield {"type": "error", "message": f"Archive's extracted contents exceed the {max_mb}MB limit."}
                    return

                logger.info(f"Zip upload for assessment '{assessment_id}': {len(members)} member(s) to inspect.")
                yield {"type": "start", "total": len(members)}

                # Skip-filtering and the actual member reads stay sequential
                # here, inside the `with` block - zipfile.ZipFile isn't safe
                # to read from concurrently (it seeks a shared file handle),
                # and this pass is fast (in-memory, no network I/O) so there's
                # nothing to gain from parallelizing it anyway. Everything
                # slow (S3 write, extract, embed, DB write) happens after the
                # archive is closed, from plain bytes already held in memory.
                for index, info in enumerate(members, start=1):
                    member_name = info.filename
                    base_name = os.path.basename(member_name.rstrip("/"))
                    lower_path = member_name.lower()

                    if not base_name or base_name.lower() in _ZIP_IGNORED_NAMES:
                        continue
                    if any(lower_path.startswith(prefix.lower()) for prefix in _ZIP_IGNORED_PREFIXES):
                        continue
                    if base_name.startswith("."):
                        continue

                    ext = os.path.splitext(base_name)[1].lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        reason = f"unsupported file type '{ext or '(none)'}'"
                        skipped.append((base_name, reason))
                        logger.info(f"Zip member '{base_name}' skipped for assessment '{assessment_id}': {reason}")
                        yield {
                            "type": "member_skipped",
                            "filename": base_name,
                            "index": index,
                            "total": len(members),
                            "reason": reason,
                        }
                        continue

                    if info.file_size > settings.MAX_UPLOAD_SIZE_BYTES:
                        max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
                        reason = f"exceeds the {max_mb}MB per-file limit"
                        skipped.append((base_name, reason))
                        logger.info(f"Zip member '{base_name}' skipped for assessment '{assessment_id}': {reason}")
                        yield {
                            "type": "member_skipped",
                            "filename": base_name,
                            "index": index,
                            "total": len(members),
                            "reason": reason,
                        }
                        continue

                    member_bytes = await run_in_threadpool(archive.read, info)
                    member_content_type = mimetypes.guess_type(base_name)[0] or "application/octet-stream"
                    to_process.append((index, base_name, member_bytes, member_content_type))

            for index, base_name, _, _ in to_process:
                yield {"type": "member_start", "filename": base_name, "index": index, "total": len(members)}

            # Fan out the actual store+index work, bounded by a semaphore so
            # at most _MAX_CONCURRENT_ZIP_MEMBERS run at once. Each worker
            # always puts exactly one item on the queue (success or not) so
            # the drain loop below never waits on an item that isn't coming.
            queue: "asyncio.Queue[Tuple[int, str, AssessmentUpload | None, int, str | None]]" = asyncio.Queue()
            semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ZIP_MEMBERS)
            # One shared session for every member's create/update_status/
            # bulk_create writes, serialized by db_lock - not one session per
            # member. A single session is never touched by more than one
            # coroutine at a time (the lock guarantees that), which sidesteps
            # both the "concurrent sessions on one shared connection" hazard
            # (always true for the test suite's SQLite+StaticPool engine) and
            # the extra complexity of juggling N independent sessions. The
            # slow work (S3 write, extract, embed) below still runs fully
            # concurrent per member - only the brief write bursts are shared.
            session_factory = async_sessionmaker(
                bind=self.upload_repo.session.bind, expire_on_commit=False, class_=AsyncSession
            )
            write_session = session_factory()
            db_lock = asyncio.Lock()

            logger.info(
                f"Zip upload for assessment '{assessment_id}': storing+indexing {len(to_process)} member(s), "
                f"up to {_MAX_CONCURRENT_ZIP_MEMBERS} concurrently."
            )

            async def worker(index: int, base_name: str, member_bytes: bytes, member_content_type: str) -> None:
                async with semaphore:
                    try:
                        upload, chunk_count = await self._store_and_process_isolated(
                            assessment_id, base_name, member_content_type, source_type, member_bytes,
                            write_session, db_lock,
                        )
                        await queue.put((index, base_name, upload, chunk_count, None))
                    except Exception as e:
                        logger.exception(f"Zip member '{base_name}' failed unexpectedly")
                        await queue.put((index, base_name, None, 0, str(e)))

            tasks = [asyncio.create_task(worker(*item)) for item in to_process]

            results: List[Tuple[AssessmentUpload, int]] = []
            for _ in tasks:
                index, base_name, upload, chunk_count, error = await queue.get()
                if error is not None or upload is None:
                    yield {
                        "type": "member_result",
                        "filename": base_name,
                        "index": index,
                        "total": len(members),
                        "status": "failed",
                        "chunk_count": 0,
                    }
                    continue
                results.append((upload, chunk_count))
                yield {
                    "type": "member_result",
                    "filename": base_name,
                    "index": index,
                    "total": len(members),
                    "status": upload.status,
                    "chunk_count": chunk_count,
                }

            await write_session.close()

            failed_count = len(to_process) - len(results)
            logger.info(
                f"Zip upload complete for assessment '{assessment_id}': {len(results)} indexed, "
                f"{failed_count} failed, {len(skipped)} skipped (of {len(members)} total members)."
            )

            yield {
                "type": "complete",
                "extracted_count": len(results),
                "skipped_count": len(skipped),
                "uploads": [
                    {
                        "upload_id": u.id,
                        "assessment_id": u.assessment_id,
                        "filename": u.filename,
                        "content_type": u.content_type,
                        "uploaded_at": u.uploaded_at.isoformat(),
                        "source_type": u.source_type,
                        "status": u.status,
                        "chunk_count": count,
                    }
                    for u, count in results
                ],
                "skipped": [{"filename": name, "reason": reason} for name, reason in skipped],
            }
        except BadRequestException as ex:
            logger.warning(f"Zip upload for assessment '{assessment_id}' failed: {ex}")
            yield {"type": "error", "message": str(ex)}
        except Exception as ex:
            logger.exception(f"Zip upload failed mid-stream for assessment '{assessment_id}'")
            yield {"type": "error", "message": str(ex)}

    async def _store_and_process(
        self,
        assessment_id: str,
        filename: str,
        content_type: str,
        source_type: str,
        file_bytes: bytes,
    ) -> Tuple[AssessmentUpload, int]:
        """Shared by upload_document and upload_zip_archive: stores the raw
        bytes in object storage, creates the AssessmentUpload row, then runs
        the extract->chunk->embed pipeline. Assumes the assessment has
        already been validated to exist."""
        storage_key = make_upload_key(assessment_id, filename)
        # upload_bytes() does a blocking S3 PUT (or local disk write) - offload to the
        # threadpool so a slow/large upload doesn't stall the event loop for every
        # other concurrent request.
        try:
            storage_reference = await run_in_threadpool(
                self.storage.upload_bytes, storage_key, file_bytes, content_type
            )
        except Exception:
            logger.exception(f"Storage write failed for '{filename}' (assessment '{assessment_id}', key '{storage_key}')")
            raise

        upload = AssessmentUpload(
            assessment_id=assessment_id,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            source_type=source_type,
            storage_reference=storage_reference,
            status="processing",
        )
        upload = await self.upload_repo.create(upload)
        observability.record_document_uploaded(assessment_id, filename, upload.content_type, source_type)

        try:
            chunk_count = await self.document_processor.process(
                assessment_id, upload.id, file_bytes, upload.content_type, filename
            )
            upload = await self.upload_repo.update_status(upload, "processed")
            logger.info(f"Indexed upload '{upload.id}' ({filename}): {chunk_count} chunk(s).")
        except Exception:
            logger.exception(f"Document processing failed for upload '{upload.id}' ({filename})")
            upload = await self.upload_repo.update_status(upload, "failed")
            chunk_count = 0

        return upload, chunk_count

    async def _store_and_process_isolated(
        self,
        assessment_id: str,
        filename: str,
        content_type: str,
        source_type: str,
        file_bytes: bytes,
        write_session: AsyncSession,
        db_lock: asyncio.Lock,
    ) -> Tuple[AssessmentUpload, int]:
        """Same as _store_and_process(), but writes through `write_session` -
        a session shared by every member being processed concurrently in the
        same upload_zip_archive_stream() call, guarded by `db_lock` - instead
        of self.upload_repo/self.chunk_repo's request-scoped session.
        Required because a single AsyncSession is not safe to use from more
        than one coroutine at a time; `db_lock` guarantees `write_session`
        never actually is, even though many members' slow work (S3 write,
        extract, embed - none of which touch the database) runs concurrently
        around these brief locked sections."""
        storage_key = make_upload_key(assessment_id, filename)
        try:
            storage_reference = await run_in_threadpool(
                self.storage.upload_bytes, storage_key, file_bytes, content_type
            )
        except Exception:
            logger.exception(f"Storage write failed for '{filename}' (assessment '{assessment_id}', key '{storage_key}')")
            raise

        upload_repo = UploadRepository(write_session)
        upload = AssessmentUpload(
            assessment_id=assessment_id,
            filename=filename,
            content_type=content_type or "application/octet-stream",
            source_type=source_type,
            storage_reference=storage_reference,
            status="processing",
        )
        async with db_lock:
            upload = await upload_repo.create(upload)
        observability.record_document_uploaded(assessment_id, filename, upload.content_type, source_type)

        try:
            chunk_repo = DocumentChunkRepository(write_session)
            document_processor = DocumentProcessingService(chunk_repo)
            chunk_count = await document_processor.process(
                assessment_id, upload.id, file_bytes, upload.content_type, filename, db_lock=db_lock
            )
            async with db_lock:
                upload = await upload_repo.update_status(upload, "processed")
            logger.info(f"Indexed upload '{upload.id}' ({filename}): {chunk_count} chunk(s).")
        except Exception:
            logger.exception(f"Document processing failed for upload '{upload.id}' ({filename})")
            async with db_lock:
                upload = await upload_repo.update_status(upload, "failed")
            chunk_count = 0

        return upload, chunk_count

    async def list_uploads(self, assessment_id: str) -> Sequence[Tuple[AssessmentUpload, int]]:
        await self._require_assessment(assessment_id)
        uploads = await self.upload_repo.list_for_assessment(assessment_id)
        # One grouped query for every upload's chunk count instead of a
        # per-upload COUNT round trip (was N+1 - see count_for_uploads).
        counts = await self.chunk_repo.count_for_uploads([u.id for u in uploads])
        return [(u, counts.get(u.id, 0)) for u in uploads]
