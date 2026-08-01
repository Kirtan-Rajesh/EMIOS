"""ORM entity for a migration assessment (the root aggregate of the persistence layer)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Assessment(Base):
    """A single customer migration assessment (lifecycle: created -> ... -> complete/failed)."""

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_cloud: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    # Nullable so pre-existing rows created before per-user ownership was
    # tracked don't break - they're simply not visible in anyone's filtered
    # list anymore (see AssessmentRepository.list_for_user).
    created_by: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    uploads: Mapped[List["AssessmentUpload"]] = relationship(
        "AssessmentUpload", back_populates="assessment", cascade="all, delete-orphan"
    )
    waves: Mapped[List["MigrationWave"]] = relationship(
        "MigrationWave", back_populates="assessment", cascade="all, delete-orphan"
    )
    nodes: Mapped[List["AssessmentNode"]] = relationship(
        "AssessmentNode", back_populates="assessment", cascade="all, delete-orphan"
    )
    edges: Mapped[List["AssessmentEdge"]] = relationship(
        "AssessmentEdge", back_populates="assessment", cascade="all, delete-orphan"
    )
    simulation: Mapped[Optional["AssessmentSimulation"]] = relationship(
        "AssessmentSimulation", back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    agent_runs: Mapped[List["AgentRun"]] = relationship(
        "AgentRun", back_populates="assessment", cascade="all, delete-orphan"
    )
    report: Mapped[Optional["AssessmentReport"]] = relationship(
        "AssessmentReport", back_populates="assessment", cascade="all, delete-orphan", uselist=False
    )
    document_chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="assessment", cascade="all, delete-orphan"
    )
