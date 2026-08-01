"""ORM entity for a compiled report snapshot (one per assessment - upsert on rerun)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class AssessmentReport(Base):
    """A compiled, deterministic report snapshot built from an assessment's stored
    simulation result + migration waves. One assessment has one report snapshot
    (upsert/replace on repeat generation, not an unbounded history).

    ``feedback_rating``/``feedback_comment`` are the simplified "human review"
    step (thumbs up/down + optional comment on the generated report - no
    reviewer role, no approval gating). ``final_migration_plan`` holds the
    distinct final-pass LLM output from POST .../migration-plan, kept on this
    same row rather than a new table since it's still fundamentally "the report
    for this assessment," just a later stage of it.
    """

    __tablename__ = "assessment_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    migration_waves: Mapped[Any] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Any] = mapped_column(JSON, nullable=True)
    # No onupdate=_utcnow here on purpose: SQLAlchemy's onupdate fires on ANY UPDATE
    # to this row, including submit_feedback()/generate_migration_plan() calls that
    # only touch feedback_*/final_migration_plan - that would make generated_at
    # silently jump forward on updates that didn't actually regenerate the report.
    # ReportService.generate_report() sets this column explicitly instead.
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    feedback_rating: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    final_migration_plan: Mapped[Any] = mapped_column(JSON, nullable=True)
    final_plan_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Bumped each time executive_summary/risk_summary/migration_waves/recommendations
    # actually change (full regenerate or a feedback-driven revision) - mirrors into a
    # new ReportRevision snapshot row each time, so history can be listed/viewed.
    current_version: Mapped[int] = mapped_column(default=1, nullable=False)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="report")


class ReportRevision(Base):
    """An immutable snapshot of a report's content at one version. Written
    every time ReportService produces new content for a report - either a full
    recompute (ReportService.generate_report) or a feedback-targeted revision
    (ReportService.revise_report). Read-only history: there is no "revert"
    endpoint, only list/view of past versions.
    """

    __tablename__ = "report_revisions"
    __table_args__ = (
        # Two concurrent generate_report()/revise_report() calls for the same
        # assessment can both read the same `current_version` and compute the
        # same `next_version` before either commits (see
        # ReportService._persist_new_version) - without this constraint both
        # inserts would silently succeed with a duplicate version number, and
        # a later get_revision() lookup (scalar_one_or_none, expecting at most
        # one row) would raise MultipleResultsFound. The constraint turns that
        # into a catchable IntegrityError instead - see
        # ReportRepository.add_revision()'s retry-with-recomputed-version.
        UniqueConstraint("report_id", "version", name="uq_report_revision_report_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    report_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessment_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "generate" | "feedback"

    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    readiness_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    migration_waves: Mapped[Any] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Any] = mapped_column(JSON, nullable=True)

    # Which of the four fields above changed vs. the prior version - null for the
    # first version of a report (nothing to diff against) or a full regenerate
    # (source="generate" always touches all of them).
    changed_sections: Mapped[Any] = mapped_column(JSON, nullable=True)
    # The feedback text that produced this revision (source="feedback" only).
    feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
