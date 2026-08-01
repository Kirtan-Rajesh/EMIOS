"""ORM entity for a persisted simulation result (one per assessment - upsert on rerun)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class AssessmentSimulation(Base):
    """The most recent cascading-failure + Monte Carlo simulation result for an
    assessment. Most of the payload is stored as JSON (mirrors
    ``MigrationWave.risk_summary``'s approach); the guide's dashboard-style
    numeric fields get dedicated indexed columns since they imply future querying.
    """

    __tablename__ = "assessment_simulations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    already_migrated: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)
    impacted_services: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)
    critical_paths: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)
    monte_carlo: Mapped[Any] = mapped_column(JSON, nullable=True)
    revenue_at_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_hosting_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    potential_savings: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="simulation")
