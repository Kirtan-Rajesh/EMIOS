"""ORM entity for a single embedded chunk of an uploaded document (RAG retrieval)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class DocumentChunk(Base):
    """Metadata for one text chunk extracted from an AssessmentUpload. The
    embedding vector itself lives in Qdrant (see app/services/vector_search_service.py) -
    this row just tracks which chunk of which upload maps to which Qdrant point,
    plus the chunk text itself for citing back to the source in RAG answers.
    ``assessment_id`` duplicates ``upload.assessment_id`` deliberately - it's the
    hot-path filter for RAG retrieval (search within one assessment's documents),
    so it gets its own indexed column rather than requiring a join through
    AssessmentUpload on every search.
    """

    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    upload_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessment_uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    qdrant_point_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    upload: Mapped["AssessmentUpload"] = relationship("AssessmentUpload", back_populates="chunks")
    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="document_chunks")
