"""Pydantic v2 response schema for the Document Upload module.

Requests are multipart/form-data (a real file + a source_type field), not
JSON - see app/api/v1/uploads.py - so there is no request schema here, only
the response shape.
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel


class UploadResponse(BaseModel):
    upload_id: str
    assessment_id: str
    filename: str
    content_type: str
    uploaded_at: datetime
    source_type: str
    status: str
    chunk_count: int = 0


class SkippedZipEntry(BaseModel):
    filename: str
    reason: str


class ZipUploadResponse(BaseModel):
    """Response for POST /assessments/{id}/uploads/zip: one UploadResponse per
    extracted member that was stored + indexed, plus the members that were
    ignored (unsupported extension, over the per-file size cap, macOS
    sidecar files, etc.) and why."""

    uploads: List[UploadResponse]
    skipped: List[SkippedZipEntry]
    extracted_count: int
