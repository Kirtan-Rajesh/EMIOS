"""Object storage for uploaded documents: Amazon S3, with a local-disk fallback.

Follows the same "connect once at startup, degrade gracefully" house style as
app/core/db.py's Neo4j/Qdrant clients: init_storage() is called from main.py's
startup event and sets the module-level `s3_client`; if S3 isn't reachable (no
credentials, no network, bucket doesn't exist), ObjectStorage falls back to a
local directory instead of hard-failing, so uploads still work without AWS
credentials configured (local dev, tests, CI).

Per that same convention, other modules must do `from app.core import storage as
core_storage` and reference `core_storage.s3_client` dynamically - never
`from app.core.storage import s3_client` - so they see the real client once
init_storage() sets it rather than a stale None captured at import time.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from app.core.config import get_boto3_client, settings

logger = logging.getLogger("emios")

# Global client, set by init_storage() - see module docstring.
s3_client = None

try:
    import boto3  # noqa: F401
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def init_storage() -> None:
    """Best-effort S3 connection. Call once from the FastAPI startup event."""
    global s3_client
    if not HAS_BOTO3:
        logger.warning("boto3 not installed. Document storage will use local disk fallback.")
        s3_client = None
        return
    try:
        client = get_boto3_client("s3")
        client.head_bucket(Bucket=settings.S3_BUCKET_NAME)
        s3_client = client
        logger.info(f"Successfully connected to S3 bucket '{settings.S3_BUCKET_NAME}'.")
    except Exception as e:
        logger.warning(
            f"Could not reach S3 bucket '{settings.S3_BUCKET_NAME}': {e}. "
            f"Document storage will use local disk fallback under '{settings.LOCAL_STORAGE_DIR}'."
        )
        s3_client = None


def make_upload_key(assessment_id: str, filename: str) -> str:
    """Builds a collision-safe storage key: assessments/{assessment_id}/{uuid}_{filename}."""
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"assessments/{assessment_id}/{uuid.uuid4().hex}_{safe_name}"


class ObjectStorage:
    """Stores/retrieves raw document bytes. Prefers S3 (module-level `s3_client`,
    set by init_storage()); falls back to local disk under settings.LOCAL_STORAGE_DIR
    if S3 is unreachable. Cheap to construct - no I/O happens in __init__, so it's
    safe to instantiate fresh per request via FastAPI's Depends()."""

    def _local_path(self, key: str) -> Path:
        path = Path(settings.LOCAL_STORAGE_DIR) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        """Stores `data` under `key`. Returns a storage reference string
        (`s3://bucket/key` or `file://local/absolute/path`) for
        AssessmentUpload.storage_reference."""
        if s3_client:
            try:
                s3_client.put_object(
                    Bucket=settings.S3_BUCKET_NAME, Key=key, Body=data, ContentType=content_type
                )
                return f"s3://{settings.S3_BUCKET_NAME}/{key}"
            except Exception as e:
                logger.warning(f"S3 upload failed for key '{key}': {e}. Falling back to local disk.")

        local_path = self._local_path(key)
        local_path.write_bytes(data)
        return f"file://{local_path.resolve()}"

    def get_bytes_by_key(self, key: str) -> bytes:
        """Reads bytes written by upload_bytes(key, ...) directly by key, for
        callers that only know the deterministic key (not the storage_reference
        string upload_bytes returned and that the caller may never have
        persisted - see discovery_service.py's fixed discovery-CSV keys, which
        are recomputed rather than looked up). Tries S3 first if active
        (mirroring upload_bytes's own S3-preferred, local-fallback write path),
        then local disk - a key could be on either if a prior S3 write
        transiently failed. Raises FileNotFoundError if neither has it."""
        if s3_client:
            try:
                response = s3_client.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
                return response["Body"].read()
            except Exception:
                pass  # fall through to local disk

        local_path = self._local_path(key)
        if not local_path.exists():
            raise FileNotFoundError(f"No object found for key '{key}' in S3 or local disk.")
        return local_path.read_bytes()

    def get_bytes(self, storage_reference: str) -> bytes:
        """Reads back bytes from a storage_reference produced by upload_bytes()."""
        if storage_reference.startswith("s3://"):
            if not s3_client:
                raise RuntimeError(
                    f"Cannot read '{storage_reference}': no active S3 client and this "
                    f"reference is not a local file."
                )
            _, _, rest = storage_reference.partition("s3://")
            bucket, _, key = rest.partition("/")
            response = s3_client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()

        if storage_reference.startswith("file://"):
            path = Path(storage_reference[len("file://"):])
            return path.read_bytes()

        raise ValueError(f"Unrecognized storage reference: '{storage_reference}'")
