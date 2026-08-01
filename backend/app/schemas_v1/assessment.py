"""Pydantic v2 request/response schemas for the Assessment Lifecycle module."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Lifecycle statuses called out explicitly in the task guide, plus the initial
# "created" state a freshly-registered assessment starts in.
AssessmentStatus = Literal["created", "uploading", "analyzing", "complete", "failed"]


class AssessmentCreateRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    project_name: str = Field(..., min_length=1, max_length=255)
    target_cloud: str = Field(..., min_length=1, max_length=64)
    status: AssessmentStatus = "created"


class AssessmentStatusUpdateRequest(BaseModel):
    status: AssessmentStatus


class AssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessment_id: str
    customer_name: str
    project_name: str
    target_cloud: str
    status: str
    created_at: datetime
    updated_at: datetime
