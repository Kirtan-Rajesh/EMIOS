"""Tests for the /api/v1 Simulation Result module (run / retrieve).

Covers: happy path (run against a persisted graph, then retrieve), 400 when no
graph has been posted yet, 404 for a nonexistent assessment, and that rerunning
upserts (replaces) rather than duplicating the stored result.
"""

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
        {"id": "monolith", "name": "Monolith", "annual_cost": 100000.0, "revenue_impact": 5000.0},
        {"id": "auth_service", "name": "Auth Service", "annual_cost": 40000.0, "revenue_impact": 2000.0},
        {"id": "user_db", "name": "User DB", "type": "Database", "annual_cost": 80000.0},
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


async def test_run_simulation_happy_path(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/simulate",
        json={"target_id": "user_db", "already_migrated": []},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert data["target_id"] == "user_db"
    assert isinstance(data["impacted_services"], list)
    assert isinstance(data["critical_paths"], list)
    assert data["total_hosting_cost"] == pytest.approx(220000.0)
    assert "monte_carlo" in data and isinstance(data["monte_carlo"], dict)


async def test_run_simulation_no_graph_yet(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/simulate",
        json={"target_id": "user_db"},
    )

    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_run_simulation_nonexistent_assessment(v1_client):
    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/simulate", json={"target_id": "user_db"}
    )
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_get_simulation_before_run(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/simulate")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_get_simulation_after_run(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/simulate", json={"target_id": "user_db"}
    )

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/simulate")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["target_id"] == "user_db"


async def test_rerun_simulation_upserts(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/simulate", json={"target_id": "user_db"}
    )
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/simulate", json={"target_id": "monolith"}
    )

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/simulate")
    assert response.json()["data"]["target_id"] == "monolith"


async def test_run_simulation_missing_target_id(v1_client):
    assessment_id = await _create_assessment_with_graph(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/simulate", json={})
    assert response.status_code == 422
