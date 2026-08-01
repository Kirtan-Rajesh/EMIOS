"""Aggregator for the /api/v1/* router - mounted in main.py with prefix="/api/v1".

This is a deliberately separate surface from the legacy app/api/endpoints.py
router (mounted at /api/*), which stays untouched. See docs/hackathon_team_task_guide.html
for the persistence-layer spec this implements.
"""

from fastapi import APIRouter

from app.api.v1 import agent_runs, assessments, auth, chat, dashboard, discovery, graph, reports, simulate, uploads, waves

router = APIRouter()
router.include_router(auth.router)
router.include_router(assessments.router)
router.include_router(uploads.router)
router.include_router(discovery.router)
router.include_router(waves.router)
router.include_router(graph.router)
router.include_router(simulate.router)
router.include_router(agent_runs.router)
router.include_router(reports.router)
router.include_router(dashboard.router)
router.include_router(chat.router)

__all__ = ["router"]
