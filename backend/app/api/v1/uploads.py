"""Document Upload routes: upload a real file for an assessment (stored in S3 +
indexed for RAG retrieval) / upload a zip archive of several documents at
once / list uploads for an assessment."""

import json
import logging
import os
from typing import List, Tuple

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_upload_service
from app.entities.upload import AssessmentUpload
from app.schemas_v1.envelope import success_envelope
from app.schemas_v1.upload import UploadResponse, ZipUploadResponse
from app.services_v1.upload_service import ALLOWED_EXTENSIONS, UploadService

logger = logging.getLogger("emios")

router = APIRouter(tags=["Uploads"])


def _to_response(upload: AssessmentUpload, chunk_count: int) -> dict:
    return UploadResponse(
        upload_id=upload.id,
        assessment_id=upload.assessment_id,
        filename=upload.filename,
        content_type=upload.content_type,
        uploaded_at=upload.uploaded_at,
        source_type=upload.source_type,
        status=upload.status,
        chunk_count=chunk_count,
    ).model_dump(mode="json")


@router.post("/assessments/{assessment_id}/uploads", status_code=status.HTTP_201_CREATED)
async def upload_document(
    assessment_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("manual"),
    service: UploadService = Depends(get_upload_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Uploads a company document (PDF/DOCX/PPTX/XLSX/CSV/JSON/text) for an assessment.
    Stores the raw file (S3 or local-disk fallback) and indexes it for RAG
    retrieval (extract -> chunk -> embed -> Qdrant). 404s if the assessment
    does not exist. `status` in the response is "processed" if indexing
    succeeded, "failed" if it didn't - the file itself is always stored
    either way."""
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    logger.info(f"POST /uploads for assessment '{assessment_id}': '{filename}' ({file.content_type or 'unknown type'})")
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning(f"Upload rejected for assessment '{assessment_id}': unsupported extension '{ext or '(none)'}'.")
        raise BadRequestException(
            f"Unsupported file type '{ext or '(none)'}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )

    # Read at most MAX_UPLOAD_SIZE_BYTES + 1 bytes so an oversized upload is capped
    # in memory rather than fully buffered before this check runs.
    max_size = settings.MAX_UPLOAD_SIZE_BYTES
    file_bytes = await file.read(max_size + 1)
    if len(file_bytes) > max_size:
        logger.warning(f"Upload rejected for assessment '{assessment_id}': '{filename}' exceeds {max_size} bytes.")
        raise BadRequestException(f"File exceeds the {max_size // (1024 * 1024)}MB upload limit.")

    upload, chunk_count = await service.upload_document(
        assessment_id=assessment_id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        source_type=source_type,
        file_bytes=file_bytes,
    )
    return success_envelope(_to_response(upload, chunk_count), message="Document uploaded successfully.")


@router.post("/assessments/{assessment_id}/uploads/zip", status_code=status.HTTP_201_CREATED)
async def upload_zip(
    assessment_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("manual"),
    service: UploadService = Depends(get_upload_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Uploads a zip archive of company documents for an assessment. The
    archive is extracted in memory; every member with an allowed extension
    (PDF/DOCX/PPTX/XLSX/CSV/JSON/text) is stored and indexed exactly like a
    single-file upload, becoming its own AssessmentUpload row. Members with
    an unsupported extension, over the per-file size limit, or macOS sidecar
    files (__MACOSX/, .DS_Store) are silently skipped and listed in
    `skipped` rather than failing the whole request. 404s if the assessment
    does not exist; 400s if the archive isn't a valid zip or exceeds the
    configured member-count/uncompressed-size caps."""
    filename = file.filename or "archive.zip"
    ext = os.path.splitext(filename)[1].lower()
    logger.info(f"POST /uploads/zip for assessment '{assessment_id}': '{filename}'")
    if ext != ".zip":
        logger.warning(f"Zip upload rejected for assessment '{assessment_id}': extension '{ext or '(none)'}' is not .zip.")
        raise BadRequestException(f"Expected a .zip file, got '{ext or '(none)'}'.")

    # Read at most MAX_ZIP_UPLOAD_SIZE_BYTES + 1 bytes so an oversized archive is
    # capped in memory rather than fully buffered before this check runs.
    max_size = settings.MAX_ZIP_UPLOAD_SIZE_BYTES
    file_bytes = await file.read(max_size + 1)
    if len(file_bytes) > max_size:
        logger.warning(f"Zip upload rejected for assessment '{assessment_id}': '{filename}' exceeds {max_size} bytes.")
        raise BadRequestException(f"Archive exceeds the {max_size // (1024 * 1024)}MB upload limit.")

    uploads, skipped = await service.upload_zip_archive(
        assessment_id=assessment_id,
        content_type=file.content_type or "application/zip",
        source_type=source_type,
        file_bytes=file_bytes,
    )
    # upload_zip_archive() returns plain dicts (one per UploadResponse field)
    # rather than AssessmentUpload entities - members are processed
    # concurrently, each through its own short-lived DB session, so there's
    # no single request-scoped entity left to build a response from the old
    # way (see UploadService._store_and_process_isolated).
    response = ZipUploadResponse(
        uploads=[UploadResponse(**u) for u in uploads],
        skipped=[{"filename": name, "reason": reason} for name, reason in skipped],
        extracted_count=len(uploads),
    )
    return success_envelope(
        response.model_dump(mode="json"),
        message=f"Archive processed: {len(uploads)} document(s) uploaded, {len(skipped)} skipped.",
    )


@router.post("/assessments/{assessment_id}/uploads/zip/stream")
async def upload_zip_stream(
    assessment_id: str,
    file: UploadFile = File(...),
    source_type: str = Form("manual"),
    service: UploadService = Depends(get_upload_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Same pipeline as POST .../uploads/zip, streamed as Server-Sent Events
    (`text/event-stream`) so a UI can show live per-file progress instead of
    a single blocking call - each member's store+index step makes a real
    embedding-model call, so a multi-file archive is inherently sequential
    and the one-shot version can legitimately take minutes with nothing to
    show for it. Event `type`s: start, member_start, member_result,
    member_skipped, complete, error. The archive itself, the file's own
    validation (must be .zip, under the size cap), and the assessment's
    existence are all checked eagerly, before the stream begins, so those
    cases still return a normal 400/404 rather than a 200 stream that either
    immediately emits an error event or - for a bad assessment_id raised from
    deep inside the generator - silently closes with no event and no error at
    all, since a StreamingResponse's 200 status is sent before its generator
    is ever advanced (see UploadService.ensure_assessment_exists's docstring).
    """
    filename = file.filename or "archive.zip"
    ext = os.path.splitext(filename)[1].lower()
    logger.info(f"POST /uploads/zip/stream for assessment '{assessment_id}': '{filename}'")
    if ext != ".zip":
        logger.warning(f"Zip upload rejected for assessment '{assessment_id}': extension '{ext or '(none)'}' is not .zip.")
        raise BadRequestException(f"Expected a .zip file, got '{ext or '(none)'}'.")

    max_size = settings.MAX_ZIP_UPLOAD_SIZE_BYTES
    file_bytes = await file.read(max_size + 1)
    if len(file_bytes) > max_size:
        logger.warning(f"Zip upload rejected for assessment '{assessment_id}': '{filename}' exceeds {max_size} bytes.")
        raise BadRequestException(f"Archive exceeds the {max_size // (1024 * 1024)}MB upload limit.")

    await service.ensure_assessment_exists(assessment_id)

    async def event_source():
        try:
            async for event in service.upload_zip_archive_stream(
                assessment_id=assessment_id,
                content_type=file.content_type or "application/zip",
                source_type=source_type,
                file_bytes=file_bytes,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            # Defense in depth: upload_zip_archive_stream() already catches its
            # own exceptions and yields a terminal {"type": "error"} event, so
            # this should never actually trigger - but if something new is
            # ever added that raises past that boundary, log it loudly here
            # instead of letting it vanish as a silent, unexplained dropped
            # connection (exactly the failure mode this whole route's eager
            # checks above exist to avoid).
            logger.exception(f"Zip upload stream for assessment '{assessment_id}' raised past its own error handling")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Unexpected server error during upload.'})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/assessments/{assessment_id}/uploads")
async def list_uploads(
    assessment_id: str,
    service: UploadService = Depends(get_upload_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Lists all uploads recorded for an assessment. 404s if the assessment does not exist."""
    uploads: List[Tuple[AssessmentUpload, int]] = list(await service.list_uploads(assessment_id))
    return success_envelope(
        [_to_response(u, count) for u, count in uploads], message="Uploads retrieved successfully."
    )
