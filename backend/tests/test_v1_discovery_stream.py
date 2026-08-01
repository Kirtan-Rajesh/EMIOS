"""Tests for the Document Discovery streaming endpoint
(POST /api/v1/assessments/{id}/discover/stream) and the non-streaming
POST .../discover, which now shares the same underlying implementation
(DiscoveryService.run_discovery_stream) - see app/services_v1/discovery_service.py.

No LLM provider is configured in this test environment (the autouse
_no_real_llm_credentials fixture in conftest.py blanks every provider
credential), so LlmPromptExtractor deterministically contributes 0
nodes/0 edges with an "LLM extraction unavailable" warning for any document
none of the structured extractors claim - exercised directly below via a
plain .txt upload.
"""

import csv
import io
import json

import pytest

pytestmark = pytest.mark.asyncio

METADATA_CSV = (
    "System ID,System Name,Category,Priority,Migration Complexity,Runtime,Annual Hosting Cost ($)\n"
    "order_svc,Order Service,Microservice,High,Medium,Java 17,95000\n"
    "inventory_svc,Inventory Service,Microservice,High,Medium,Java 17,80000\n"
)


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


async def _upload(client, assessment_id, filename, content, content_type="text/plain"):
    resp = await client.post(
        f"/api/v1/assessments/{assessment_id}/uploads",
        files={"file": (filename, content, content_type)},
    )
    assert resp.status_code == 201, resp.text


async def _collect_events(client, assessment_id):
    events = []
    async with client.stream(
        "POST", f"/api/v1/assessments/{assessment_id}/discover/stream"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


async def test_discover_stream_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await _upload(v1_client, assessment_id, "System_Metadata_Catalog.csv", METADATA_CSV.encode(), "text/csv")
    await _upload(v1_client, assessment_id, "notes.txt", b"This system handles order processing.")

    events = await _collect_events(v1_client, assessment_id)
    types = [e["type"] for e in events]

    assert types[0] == "start"
    assert events[0]["total_documents"] == 2
    assert types[-1] == "complete"
    assert "merging" in types
    assert "csv_generated" in types
    assert "persisting" in types

    doc_starts = [e for e in events if e["type"] == "document_start"]
    doc_results = [e for e in events if e["type"] == "document_result"]
    assert {e["filename"] for e in doc_starts} == {"System_Metadata_Catalog.csv", "notes.txt"}
    assert len(doc_results) == 2

    metadata_result = next(r for r in doc_results if r["filename"] == "System_Metadata_Catalog.csv")
    assert metadata_result["extractor"] == "MetadataExtractor"
    assert metadata_result["nodes_found"] == 2
    assert metadata_result["confidence"] == 1.0

    llm_result = next(r for r in doc_results if r["filename"] == "notes.txt")
    assert llm_result["extractor"] == "LlmPromptExtractor"
    assert llm_result["nodes_found"] == 0
    assert llm_result["confidence"] == 0.55

    csv_event = next(e for e in events if e["type"] == "csv_generated")
    assert csv_event["node_count"] == 2
    assert csv_event["edge_count"] == 0
    parsed_nodes = list(csv.DictReader(io.StringIO(csv_event["nodes_csv"])))
    assert len(parsed_nodes) == 2
    assert {n["id"] for n in parsed_nodes} == {"order_svc", "inventory_svc"}
    assert csv_event["edges_csv"].strip() == "source,target,type,criticality,is_discovered"

    complete_event = events[-1]
    assert complete_event["status"] == "graph_updated"
    assert complete_event["node_count"] == 2
    assert complete_event["edge_count"] == 0
    assert complete_event["graph_status"].startswith("persisted")

    # The whole point: no manual POST .../graph call anywhere above - the graph
    # should already be persisted purely from the streamed discovery run.
    graph_resp = await v1_client.get(f"/api/v1/assessments/{assessment_id}/graph")
    assert graph_resp.status_code == 200
    graph_data = graph_resp.json()["data"]
    assert graph_data["assessment_id"] == assessment_id
    assert {n["id"] for n in graph_data["nodes"]} == {"order_svc", "inventory_svc"}
    assert len(graph_data["edges"]) == 0


async def test_discover_stream_nonexistent_assessment_is_404_not_a_stream(v1_client):
    async with v1_client.stream(
        "POST", "/api/v1/assessments/does-not-exist/discover/stream"
    ) as response:
        assert response.status_code == 404
        body = b"".join([chunk async for chunk in response.aiter_bytes()])
    assert json.loads(body)["success"] is False


async def test_discover_stream_no_uploads_is_400_not_a_stream(v1_client):
    assessment_id = await _create_assessment(v1_client)

    async with v1_client.stream(
        "POST", f"/api/v1/assessments/{assessment_id}/discover/stream"
    ) as response:
        assert response.status_code == 400
        body = b"".join([chunk async for chunk in response.aiter_bytes()])
    assert json.loads(body)["success"] is False


async def test_discover_non_streaming_still_works(v1_client):
    """Regression check: POST .../discover (non-streaming) keeps its original
    one-shot response shape now that it's a thin wrapper over run_discovery_stream()."""
    assessment_id = await _create_assessment(v1_client)
    await _upload(v1_client, assessment_id, "System_Metadata_Catalog.csv", METADATA_CSV.encode(), "text/csv")

    resp = await v1_client.post(f"/api/v1/assessments/{assessment_id}/discover")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["assessment_id"] == assessment_id
    assert data["status"] == "graph_updated"
    assert data["node_count"] == 2
    assert data["edge_count"] == 0
    assert "extraction_report" in data
    assert data["extraction_report"]["per_document"][0]["extractor"] == "MetadataExtractor"


async def test_download_discovery_csv_404_before_any_run(v1_client):
    assessment_id = await _create_assessment(v1_client)

    resp = await v1_client.get(f"/api/v1/assessments/{assessment_id}/discover/nodes.csv")
    assert resp.status_code == 404
    assert resp.json()["success"] is False

    resp = await v1_client.get(f"/api/v1/assessments/{assessment_id}/discover/edges.csv")
    assert resp.status_code == 404


async def test_download_discovery_csv_404_nonexistent_assessment(v1_client):
    resp = await v1_client.get("/api/v1/assessments/does-not-exist/discover/nodes.csv")
    assert resp.status_code == 404


async def test_download_discovery_csv_after_run(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await _upload(v1_client, assessment_id, "System_Metadata_Catalog.csv", METADATA_CSV.encode(), "text/csv")

    discover_resp = await v1_client.post(f"/api/v1/assessments/{assessment_id}/discover")
    assert discover_resp.status_code == 201

    nodes_resp = await v1_client.get(f"/api/v1/assessments/{assessment_id}/discover/nodes.csv")
    assert nodes_resp.status_code == 200
    assert nodes_resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in nodes_resp.headers["content-disposition"]
    parsed_nodes = list(csv.DictReader(io.StringIO(nodes_resp.text)))
    assert {n["id"] for n in parsed_nodes} == {"order_svc", "inventory_svc"}

    edges_resp = await v1_client.get(f"/api/v1/assessments/{assessment_id}/discover/edges.csv")
    assert edges_resp.status_code == 200
    assert edges_resp.text.strip() == "source,target,type,criticality,is_discovered"


async def test_discover_stream_falls_back_when_semantic_merge_times_out(v1_client, monkeypatch):
    """A slow/unresponsive semantic-merge call must not hang the whole stream -
    it should time out and fall back to fast exact-match-only merging. Uses a
    real (but tiny) timeout rather than mocking asyncio.wait_for itself, so
    nothing outside this one call path is touched."""
    import time

    import app.services_v1.discovery_service as discovery_service_module

    real_merge = discovery_service_module.merge_extraction_results

    def patched_merge(all_results, enable_semantic_merge=True):
        # Never actually calls real_merge(..., enable_semantic_merge=True): the
        # "slow" branch only needs to be slow, not real - avoids leaving an
        # orphaned background thread (run_in_threadpool can't cancel a real OS
        # thread once asyncio.wait_for gives up on it) that could still reach
        # get_embedding_provider() after this test's fixtures have torn down
        # and the credential-blanking window has closed.
        if enable_semantic_merge:
            time.sleep(0.3)  # longer than the monkeypatched timeout below
        return real_merge(all_results, enable_semantic_merge=False)

    monkeypatch.setattr(discovery_service_module, "merge_extraction_results", patched_merge)
    monkeypatch.setattr(discovery_service_module, "_MERGE_TIMEOUT_SECONDS", 0.05)

    assessment_id = await _create_assessment(v1_client)
    await _upload(v1_client, assessment_id, "System_Metadata_Catalog.csv", METADATA_CSV.encode(), "text/csv")

    events = await _collect_events(v1_client, assessment_id)
    complete_event = events[-1]
    assert complete_event["type"] == "complete"
    assert complete_event["status"] == "graph_updated"
    assert complete_event["node_count"] == 2
    assert any("timed out" in w for w in complete_event["warnings"])
