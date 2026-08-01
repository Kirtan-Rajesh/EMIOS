"""Pydantic v2 response schema for the Dashboard Summary module."""

from typing import Optional

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    total_assessments: int
    completed_assessments: int
    active_assessments: int
    latest_assessment_id: Optional[str] = None
