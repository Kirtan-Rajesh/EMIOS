"""Tests for the /api/v1 Agent Run / Observability module (run planner / list
runs / stream / latest).

Runs against the same Discovery/Dependency/Planner/Risk LangGraph engine as the
legacy POST /api/plan, which has an explainable deterministic fallback when no
real LLM API key is configured (see backend/.env.example) - no network calls
happen in this test environment.
"""

import json

import pytest

pytestmark = pytest.mark.asyncio


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


_GRAPH_PAYLOAD = {
    "nodes": [
        {"id": "monolith", "name": "Monolith"},
        {"id": "auth_service", "name": "Auth Service"},
        {"id": "user_db", "name": "User DB", "type": "Database"},
    ],
    "edges": [
        {"source": "auth_service", "target": "monolith", "type": "Sync", "criticality": "High"},
        {"source": "auth_service", "target": "user_db", "type": "DB", "criticality": "High"},
    ],
}


async def _create_assessment_with_graph(client) -> str:
    assessment_id = await _create_assessment(client)
    await client.post(f"/api/v1/assessments/{assessment_id}/graph", json=_GRAPH_PAYLOAD)
    return assessment_id


async def test_run_planner_happy_path(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert isinstance(data["waves"], list) and len(data["waves"]) > 0
    assert isinstance(data["agent_runs"], list) and len(data["agent_runs"]) >= 4
    agent_names = {r["agent_name"] for r in data["agent_runs"]}
    assert "Discovery Agent" in agent_names
    assert "Planner Agent" in agent_names
    for run in data["agent_runs"]:
        assert run["status"] == "completed"
        assert run["completed_at"] is not None


async def test_run_planner_no_graph_yet(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")
    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_run_planner_nonexistent_assessment(v1_client):
    response = await v1_client.post("/api/v1/assessments/does-not-exist/agent-runs")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_list_agent_runs_empty(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs")
    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_list_agent_runs_after_run(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    run_resp = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")
    expected_count = len(run_resp.json()["data"]["agent_runs"])

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs")

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == expected_count
    for run in data:
        assert run["assessment_id"] == assessment_id
        assert isinstance(run["agent_run_id"], str) and run["agent_run_id"]


async def test_list_agent_runs_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/agent-runs")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def _collect_planner_stream_events(client, assessment_id):
    events = []
    async with client.stream(
        "POST", f"/api/v1/assessments/{assessment_id}/agent-runs/stream"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


async def test_run_planner_stream_happy_path(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    events = await _collect_planner_stream_events(v1_client, assessment_id)

    assert events[0] == {"type": "start", "assessment_id": assessment_id}
    agent_results = [e for e in events if e["type"] == "agent_result"]
    assert len(agent_results) >= 4
    agent_names = {e["agent_name"] for e in agent_results}
    assert "Discovery Agent" in agent_names
    assert "Planner Agent" in agent_names
    for e in agent_results:
        assert e["status"] == "completed"
        assert e["assessment_id"] == assessment_id

    complete = events[-1]
    assert complete["type"] == "complete"
    assert complete["assessment_id"] == assessment_id
    assert isinstance(complete["waves"], list) and len(complete["waves"]) > 0
    assert isinstance(complete["complexity"]["complexity_score"], float)
    assert isinstance(complete["cloud_readiness"]["readiness_score"], float)
    assert complete["cloud_readiness"]["recommended_platform"] in {"Azure", "AWS", "GoogleCloud"}
    assert isinstance(complete["enterprise_risk"]["risk_score"], float)
    assert isinstance(complete["recommendation"]["recommended_strategy"], str)
    assert isinstance(complete["confidence_score"], float)


async def test_run_planner_stream_persists_same_as_non_streaming(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    events = await _collect_planner_stream_events(v1_client, assessment_id)
    streamed_count = len([e for e in events if e["type"] == "agent_result"])

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs")
    data = response.json()["data"]

    assert len(data) == streamed_count


async def test_run_planner_stream_no_graph_yet(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs/stream")
    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_run_planner_stream_nonexistent_assessment(v1_client):
    response = await v1_client.post("/api/v1/assessments/does-not-exist/agent-runs/stream")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_latest_planner_result_before_any_run(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] is None


async def test_latest_planner_result_after_run(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    run_resp = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")
    original = run_resp.json()["data"]

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs/latest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assessment_id"] == assessment_id
    assert data["waves"] == original["waves"]
    assert data["risk_assessment"] == original["risk_assessment"]
    assert len(data["agent_runs"]) == len(original["agent_runs"])


async def test_latest_planner_result_after_stream(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    events = await _collect_planner_stream_events(v1_client, assessment_id)
    complete = events[-1]

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs/latest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["waves"] == complete["waves"]
    assert data["risk_assessment"] == complete["risk_assessment"]
    assert data["complexity"] == complete["complexity"]
    assert data["cloud_readiness"] == complete["cloud_readiness"]
    assert data["enterprise_risk"] == complete["enterprise_risk"]
    assert data["simulation_results"] == complete["simulation_results"]
    assert data["recommendation"] == complete["recommendation"]
    assert data["explainability"] == complete["explainability"]
    assert data["confidence_score"] == complete["confidence_score"]


async def test_latest_planner_result_reflects_most_recent_run_only(v1_client):
    """Re-running the planner (e.g. after graph changes) must make
    get_latest_result() reflect the NEW batch, not append to or conflate with
    the old one."""
    assessment_id = await _create_assessment_with_graph(v1_client)
    first_run = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")
    first_count = len(first_run.json()["data"]["agent_runs"])

    second_run = await v1_client.post(f"/api/v1/assessments/{assessment_id}/agent-runs")
    second_data = second_run.json()["data"]

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/agent-runs/latest")
    latest = response.json()["data"]

    assert len(latest["agent_runs"]) == len(second_data["agent_runs"])
    assert len(latest["agent_runs"]) == first_count  # same graph -> same stage count
    latest_ids = {r["agent_run_id"] for r in latest["agent_runs"]}
    second_ids = {r["agent_run_id"] for r in second_data["agent_runs"]}
    assert latest_ids == second_ids


async def test_latest_planner_result_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/agent-runs/latest")
    assert response.status_code == 404
    assert response.json()["success"] is False
