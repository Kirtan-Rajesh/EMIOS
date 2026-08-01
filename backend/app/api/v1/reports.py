"""Report Snapshot routes: generate / retrieve a compiled assessment report,
submit feedback on it (simplified human review), request a feedback-targeted
revision (with version history), download the current report as a PDF, and
generate the final migration plan."""

from fastapi import APIRouter, Depends, Response, status

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_report_service
from app.entities.report import AssessmentReport, ReportRevision
from app.schemas_v1.envelope import success_envelope
from app.schemas_v1.report import (
    ReportFeedbackRequest,
    ReportResponse,
    ReportRevisionDetail,
    ReportRevisionSummary,
    ReportReviseRequest,
    ReviseReportResponse,
)
from app.services_v1.report_service import ReportService

router = APIRouter(tags=["Reports"])


def _to_response(report: AssessmentReport) -> dict:
    return ReportResponse.model_validate(report).model_dump(mode="json")


def _revision_to_summary(revision: ReportRevision) -> dict:
    return ReportRevisionSummary.model_validate(revision).model_dump(mode="json")


def _revision_to_detail(revision: ReportRevision) -> dict:
    return ReportRevisionDetail.model_validate(revision).model_dump(mode="json")


@router.post("/assessments/{assessment_id}/report", status_code=status.HTTP_201_CREATED)
async def generate_report(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Compiles and stores a report snapshot from the assessment's stored
    simulation result and migration waves (upsert - regenerating replaces the
    prior snapshot and appends a new version to history). 404s if the
    assessment does not exist; 400s if no simulation has been run yet."""
    report = await service.generate_report(assessment_id)
    return success_envelope(_to_response(report), message="Assessment report generated successfully.")


@router.get("/assessments/{assessment_id}/report")
async def get_report(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Retrieves the most recently generated report snapshot for an assessment.
    404s if the assessment does not exist, or if no report has been generated yet."""
    report = await service.get_report(assessment_id)
    return success_envelope(_to_response(report), message="Assessment report retrieved successfully.")


@router.post("/assessments/{assessment_id}/report/feedback")
async def submit_report_feedback(
    assessment_id: str,
    payload: ReportFeedbackRequest,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Records a thumbs up/down + optional comment against the assessment's
    report (simplified human review - no reviewer role, no approval gate).
    404s if the assessment or its report does not exist."""
    report = await service.submit_feedback(assessment_id, payload.rating, payload.comment)
    return success_envelope(_to_response(report), message="Feedback recorded successfully.")


@router.post("/assessments/{assessment_id}/report/revise")
async def revise_report(
    assessment_id: str,
    payload: ReportReviseRequest,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Feedback-loop revision: an LLM pass decides which report section(s) the
    free-text feedback concerns and revises only those, leaving the rest
    unchanged. Persists a new version to history. 404s if the assessment or
    its report does not exist."""
    report, changed_sections = await service.revise_report(assessment_id, payload.feedback)
    response = ReviseReportResponse(**_to_response(report), changed_sections=changed_sections)
    return success_envelope(response.model_dump(mode="json"), message="Report revised successfully.")


@router.get("/assessments/{assessment_id}/report/history")
async def list_report_history(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Lists version history (metadata only - version, source, changed
    sections, feedback text, timestamp) for the assessment's report, newest
    first. 404s if the assessment or its report does not exist."""
    revisions = await service.list_revisions(assessment_id)
    return success_envelope(
        [_revision_to_summary(r) for r in revisions], message="Report history retrieved successfully."
    )


@router.get("/assessments/{assessment_id}/report/history/{version}")
async def get_report_history_version(
    assessment_id: str,
    version: int,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Retrieves the full read-only content snapshot for one past version.
    404s if the assessment, its report, or that version does not exist."""
    revision = await service.get_revision(assessment_id, version)
    return success_envelope(_revision_to_detail(revision), message="Report version retrieved successfully.")


@router.get("/assessments/{assessment_id}/report/pdf")
async def download_report_pdf(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Renders the current report snapshot to PDF and returns it as a file
    download. Not envelope-wrapped (binary body). 404s if the assessment or
    its report does not exist."""
    pdf_bytes = await service.generate_report_pdf(assessment_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report_{assessment_id}.pdf"'},
    )


@router.post("/assessments/{assessment_id}/migration-plan", status_code=status.HTTP_201_CREATED)
async def generate_migration_plan(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Generates the final migration strategy (one more LLM pass, Bedrock-
    preferred) from the compiled report and any feedback on it, persisted onto
    the same report row. 404s if the assessment or its report does not exist."""
    report = await service.generate_migration_plan(assessment_id)
    return success_envelope(_to_response(report), message="Migration plan generated successfully.")


@router.get("/assessments/{assessment_id}/migration-plan/pdf")
async def download_migration_plan_pdf(
    assessment_id: str,
    service: ReportService = Depends(get_report_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Renders just the final migration plan (not the whole report) to PDF and
    returns it as a file download. Not envelope-wrapped (binary body). 404s if
    the assessment or its report does not exist; 400s if no plan has been
    generated yet."""
    pdf_bytes = await service.generate_migration_plan_pdf(assessment_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="migration_plan_{assessment_id}.pdf"'},
    )
