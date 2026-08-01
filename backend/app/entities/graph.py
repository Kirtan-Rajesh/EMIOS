"""ORM entities for a persisted, per-assessment service dependency graph.

Mirrors the shape of ``app.models.schemas.ServiceNode``/``DependencyEdge`` (the
existing ingestion pipeline's schemas) field-for-field, so round-tripping a
``GraphData`` payload through these tables is lossless. See
``app/services_v1/graph_service.py`` for the known Neo4j-is-a-single-shared-graph
architecture constraint this module works around.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.entities.assessment import _new_id


class AssessmentNode(Base):
    """A single service/component node in an assessment's persisted graph."""

    __tablename__ = "assessment_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The external/business node id from the ingestion payload (ServiceNode.id) -
    # distinct from this row's own surrogate primary key.
    node_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="Microservice")
    business_value: Mapped[str] = mapped_column(String(32), nullable=False, default="Medium")
    revenue_impact: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    migration_complexity: Mapped[str] = mapped_column(String(32), nullable=False, default="Medium")
    base_cost: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)
    base_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Legacy")
    failure_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    runtime: Mapped[str] = mapped_column(String(64), nullable=True, default="Unknown")
    annual_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="nodes")


class AssessmentEdge(Base):
    """A single dependency edge in an assessment's persisted graph."""

    __tablename__ = "assessment_edges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    assessment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="Sync")
    criticality: Mapped[str] = mapped_column(String(32), nullable=False, default="Medium")
    is_discovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="edges")
