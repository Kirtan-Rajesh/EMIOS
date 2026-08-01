"""ORM entity recording one observability row per multi-agent negotiation stage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id, _utcnow


class AgentRun(Base):
    """A single agent execution stage (Discovery/Dependency/Planner/Risk, one row
    per negotiation-log entry) recorded when POST /assessments/{id}/agent-runs
    (or its streaming twin) runs.

    `batch_id` groups every row from one run_planner()/run_planner_stream()
    invocation together (a single negotiation can span several rows - Planner/
    Risk repeat on each renegotiation iteration) - nullable since rows written
    before this field existed won't have one; only used to reconstruct "the
    latest complete run" (app/services_v1/agent_run_service.py's
    get_latest_result()), never to merge unrelated older data.

    `final_result` carries the negotiation's authoritative, Python-computed
    output (waves/decoupling_strategies/risk_assessment - distinct from
    `summary`, which is that one stage's own narrative LLM text) - set only on
    the terminal row of a batch, so a later GET can rebuild the same shape
    POST originally returned without re-running anything or trusting an LLM's
    JSON restatement of numbers Python already computed authoritatively.

    `pipeline_metrics` is the same "terminal row only" pattern as
    `final_result`, but for the extra computed state the 12-agent Master
    Orchestrator pipeline (`run_full_assessment_stream`) produces beyond
    waves/decoupling/risk - complexity scores, enterprise risk category
    breakdown, cloud readiness/platform scores, simulation scenarios,
    recommendation, and explainability evidence. Before this field existed,
    that state was computed in-memory and thrown away once the run finished
    (see `app/agents/MASTER_ORCHESTRATOR.md`'s "Explicitly out of scope: No
    new DB persistence") - only each stage's own narrative log text survived
    in `summary`. Null for rows from the legacy 4-agent `run_planner()` path,
    which never populates this extra state at all."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    final_result: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    pipeline_metrics: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="agent_runs")
