"""Assessment Chat routes: a document-grounded (RAG) chat endpoint scoped to
one assessment - see app/services_v1/chat_service.py."""

from fastapi import APIRouter, Depends

from app.dependencies.auth import require_assessment_owner
from app.dependencies.services import get_chat_service
from app.schemas_v1.chat import ChatRequest, ChatResponse
from app.schemas_v1.envelope import success_envelope
from app.services_v1.chat_service import ChatService

router = APIRouter(tags=["Assessment Chat"])


@router.post("/assessments/{assessment_id}/chat")
async def assessment_chat(
    assessment_id: str,
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    _owner: None = Depends(require_assessment_owner),
):
    """Answers a question grounded in this assessment's uploaded documents
    (retrieved via the same per-assessment-scoped vector search Document
    Discovery's RAG path already uses) plus a summary of its digital twin
    graph, report, and simulation results (whichever have been generated so
    far). 404s if the assessment does not exist. Never fabricates - if
    nothing relevant has been discovered/uploaded yet, says so plainly rather
    than guessing, matching the honesty convention used throughout the
    Document Discovery extractors.
    """
    messages = [m.model_dump() for m in request.messages]
    result = await service.ask(assessment_id, messages)
    response = ChatResponse(**result)
    return success_envelope(response.model_dump(mode="json"), message="Chat reply generated successfully.")
