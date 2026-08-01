"""Pydantic v2 response schemas for the Agent Run / Observability module."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_run_id: str
    assessment_id: str
    agent_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    summary: Any = None
