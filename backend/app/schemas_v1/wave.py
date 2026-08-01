"""Pydantic v2 request/response schemas for the Migration Wave module."""

from datetime import datetime
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field


class WaveItem(BaseModel):
    wave_number: int = Field(..., ge=1)
    components: List[str] = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    risk_summary: Any = None


class WaveCreateRequest(BaseModel):
    """Batch payload - a planner run typically produces several waves at once."""

    waves: List[WaveItem] = Field(..., min_length=1)


class WaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    wave_id: str
    assessment_id: str
    wave_number: int
    components: List[str]
    rationale: str
    risk_summary: Any = None
    created_at: datetime
