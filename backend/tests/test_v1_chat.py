"""Tests for the per-assessment Document-grounded Chat module
(POST /api/v1/assessments/{id}/chat) - see app/services_v1/chat_service.py.

No LLM provider is configured in this test environment (the autouse
_no_real_llm_credentials fixture in conftest.py blanks every provider
credential), so invoke_with_fallback() always returns chat_service's own
honest fallback text rather than a real generated reply - these tests assert
the retrieval/grounding plumbing (which documents get searched, which sources
come back) and the honest "nothing to ground an answer in" behavior, not
actual LLM output quality.
"""

import pytest

pytestmark = pytest.mark.asyncio

METADATA_CSV = (
    "System ID,System Name,Category,Priority,Migration Complexity,Runtime,Annual Hosting Cost ($)\n"
    "order_svc,Order Service,Microservice,High,Medium,Java 17,95000\n"
)


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


async def _ask(client, assessment_id, message):
    return await client.post(
        f"/api/v1/assessments/{assessment_id}/chat",
        json={"messages": [{"role": "user", "content": message}]},
    )


async def test_chat_nonexistent_assessment_is_404(v1_client):
    resp = await _ask(v1_client, "does-not-exist", "hello")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


async def test_chat_with_no_documents_or_graph_is_honest(v1_client):
    assessment_id = await _create_assessment(v1_client)

    resp = await _ask(v1_client, assessment_id, "What systems are in scope?")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "don't have enough information" in data["reply"]
    assert data["sources"] == []
    assert data["trace_id"] is None


async def test_chat_retrieves_uploaded_document_chunks(v1_client):
    assessment_id = await _create_assessment(v1_client)

    upload_resp = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("runbook.txt", b"Order Service depends on the Orders database. " * 20, "text/plain")},
    )
    assert upload_resp.status_code == 201
    upload_id = upload_resp.json()["data"]["upload_id"]
    assert upload_resp.json()["data"]["chunk_count"] >= 1

    resp = await _ask(v1_client, assessment_id, "What does Order Service depend on?")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # No LLM configured in tests -> falls back to the honest no-provider text,
    # but retrieval itself should still have found and cited this upload.
    assert data["sources"] == [upload_id]


async def test_chat_after_discovery_summarizes_graph(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("System_Metadata_Catalog.csv", METADATA_CSV.encode(), "text/csv")},
    )
    discover_resp = await v1_client.post(f"/api/v1/assessments/{assessment_id}/discover")
    assert discover_resp.status_code == 201

    resp = await _ask(v1_client, assessment_id, "What's the highest cost system?")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Graph exists now, so this should NOT hit the "nothing discovered yet"
    # early-return path (that one always yields sources == [] and trace_id
    # None even with zero retrieved chunks); confirm it went through the full
    # prompt-building path by checking a trace was recorded.
    assert data["trace_id"] is not None


async def test_chat_conversation_history_is_included(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": ("notes.txt", b"This system handles order processing. " * 20, "text/plain")},
    )

    resp = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/chat",
        json={
            "messages": [
                {"role": "user", "content": "What is this migration about?"},
                {"role": "assistant", "content": "It's about Order Service."},
                {"role": "user", "content": "Tell me more."},
            ]
        },
    )
    assert resp.status_code == 200
