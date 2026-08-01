"""ORM entity recording metadata about a file/data upload attached to an assessment."""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class AssessmentUpload(Base):
    """Metadata record for a single upload (nodes/edges file, discovery export,
    or a company document for RAG). ``storage_reference`` is the real S3 (or
    local-disk fallback) key from app/core/storage.py. ``status`` tracks the
    document-processing pipeline for unstructured docs: uploaded -> processing
    -> processed -> failed (structured CSV/JSON uploads that feed the graph
    directly go straight to "processed" - there's nothing to chunk/embed)."""

    __tablename__ = "assessment_uploads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="uploads")
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="upload", cascade="all, delete-orphan"
    )
