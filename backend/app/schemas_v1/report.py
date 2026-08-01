"""Pydantic v2 request/response schemas for the Report Snapshot module,
including the simplified report-feedback stage, feedback-driven revisions
(with version history), and the final migration-plan stage."""

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

REPORT_SECTIONS = ("executive_summary", "risk_summary", "migration_waves", "recommendations")


class ReportFeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(None, max_length=2000)


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessment_id: str
    executive_summary: str
    readiness_score: float
    risk_summary: Any = None
    migration_waves: Any = None
    recommendations: Any = None
    generated_at: datetime
    current_version: int = 1

    feedback_rating: Optional[str] = None
    feedback_comment: Optional[str] = None
    feedback_submitted_at: Optional[datetime] = None

    final_migration_plan: Any = None
    final_plan_generated_at: Optional[datetime] = None


class ReportReviseRequest(BaseModel):
    """Free-text feedback describing what should change about the report. The
    LLM decides which of REPORT_SECTIONS the feedback concerns and revises only
    those - untouched sections are carried over unchanged."""

    feedback: str = Field(..., min_length=1, max_length=2000)


class ReviseReportResponse(ReportResponse):
    changed_sections: List[str]


class ReportRevisionSummary(BaseModel):
    """Lightweight history-list entry - metadata only, no section content."""

    model_config = ConfigDict(from_attributes=True)

    version: int
    source: Literal["generate", "feedback"]
    changed_sections: Optional[List[str]] = None
    feedback_comment: Optional[str] = None
    created_at: datetime


class ReportRevisionDetail(ReportRevisionSummary):
    """Full content snapshot for one past version, for read-only viewing."""

    executive_summary: str
    readiness_score: float
    risk_summary: Any = None
    migration_waves: Any = None
    recommendations: Any = None
