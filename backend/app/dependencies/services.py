"""Dependency-injection providers wiring repositories into services into routers.

Kept as thin factory functions so routers only ever depend on a service type via
``Depends(get_x_service)`` - they never construct repositories or sessions themselves.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.db import get_db
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.simulation_repository import SimulationRepository
from app.repositories.upload_repository import UploadRepository
from app.repositories.user_repository import UserRepository
from app.repositories.wave_repository import WaveRepository
from app.services_v1.agent_run_service import AgentRunService
from app.services_v1.assessment_service import AssessmentService
from app.services_v1.auth_service import AuthService
from app.services_v1.chat_service import ChatService
from app.services_v1.dashboard_service import DashboardService
from app.services_v1.discovery_service import DiscoveryService
from app.services_v1.graph_service import GraphService
from app.services_v1.report_service import ReportService
from app.services_v1.simulate_service import SimulateService
from app.services_v1.upload_service import UploadService
from app.services_v1.wave_service import WaveService


def get_assessment_service(db: AsyncSession = Depends(get_db)) -> AssessmentService:
    return AssessmentService(AssessmentRepository(db))


def get_upload_service(db: AsyncSession = Depends(get_db)) -> UploadService:
    return UploadService(UploadRepository(db), AssessmentRepository(db), DocumentChunkRepository(db))


def get_wave_service(db: AsyncSession = Depends(get_db)) -> WaveService:
    return WaveService(WaveRepository(db), AssessmentRepository(db))


def get_dashboard_service(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(AssessmentRepository(db))


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db))


def get_graph_service(db: AsyncSession = Depends(get_db)) -> GraphService:
    return GraphService(GraphRepository(db), AssessmentRepository(db))


def get_discovery_service(db: AsyncSession = Depends(get_db)) -> DiscoveryService:
    return DiscoveryService(
        UploadRepository(db), AssessmentRepository(db), GraphService(GraphRepository(db), AssessmentRepository(db))
    )


def get_simulate_service(db: AsyncSession = Depends(get_db)) -> SimulateService:
    return SimulateService(SimulationRepository(db), GraphRepository(db), AssessmentRepository(db))


def get_agent_run_service(db: AsyncSession = Depends(get_db)) -> AgentRunService:
    return AgentRunService(AgentRunRepository(db), GraphRepository(db), AssessmentRepository(db))


def get_report_service(db: AsyncSession = Depends(get_db)) -> ReportService:
    return ReportService(ReportRepository(db), AgentRunRepository(db), GraphRepository(db), AssessmentRepository(db))


def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(
        AssessmentRepository(db), GraphRepository(db), ReportRepository(db), SimulationRepository(db), UploadRepository(db)
    )
