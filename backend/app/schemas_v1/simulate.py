"""Pydantic v2 request/response schemas for the Simulation Result module."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class SimulateRequest(BaseModel):
    """Same shape as the legacy ``app.models.schemas.SimulationRequest``."""

    target_id: str = Field(..., min_length=1)
    already_migrated: List[str] = Field(default_factory=list)


class SimulationResultResponse(BaseModel):
    assessment_id: str
    target_id: str
    impacted_services: List[Dict[str, Any]]
    critical_paths: List[List[str]]
    revenue_at_risk: float
    total_hosting_cost: float
    potential_savings: float
    monte_carlo: Dict[str, Any]
