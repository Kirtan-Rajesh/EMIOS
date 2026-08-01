"""Dashboard Summary route: aggregate counts read from durable relational storage."""

from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.dependencies.services import get_dashboard_service
from app.entities.user import User
from app.schemas_v1.dashboard import DashboardSummaryResponse
from app.schemas_v1.envelope import success_envelope
from app.services_v1.dashboard_service import DashboardService

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/summary")
async def dashboard_summary(
    service: DashboardService = Depends(get_dashboard_service),
    current_user: User = Depends(get_current_user),
):
    """Returns the current user's own assessment counts, computed from the
    persisted (not in-memory) store."""
    summary = await service.get_summary(current_user.id)
    return success_envelope(
        DashboardSummaryResponse(**summary).model_dump(mode="json"),
        message="Dashboard summary retrieved successfully.",
    )
