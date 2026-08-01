"""ORM entity for a stored migration wave (planner output persisted per assessment)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class MigrationWave(Base):
    """A single migration wave (batch of components) planned for an assessment.

    ``components`` and ``risk_summary`` are stored using the generic ``JSON`` type
    (not Postgres ``JSONB``) so the model is portable across SQLite (tests) and
    Postgres (production) without any dialect-specific behavior.
    """

    __tablename__ = "migration_waves"
    __table_args__ = (
        UniqueConstraint("assessment_id", "wave_number", name="uq_migration_wave_assessment_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    wave_number: Mapped[int] = mapped_column(Integer, nullable=False)
    components: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="waves")
