"""Tests for the /api/v1 Assessment Graph Persistence module (persist / retrieve).

Covers: happy path round-trip, full-replace on re-post, and 404 for a
nonexistent assessment. Neo4j is not running in this test environment, so the
best-effort sync in GraphService.persist_graph is expected to report
"persisted_neo4j_sync_failed" - the relational persistence itself must still
succeed regardless.
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
        {"id": "auth_service", "name": "Auth Service", "type": "Microservice", "annual_cost": 40000.0},
        {"id": "user_db", "name": "User DB", "type": "Database", "annual_cost": 80000.0},
    ],
    "edges": [
        {"source": "auth_service", "target": "user_db", "type": "DB", "criticality": "High"},
    ],
}


async def test_persist_graph_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/graph", json=_GRAPH_PAYLOAD
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert data["node_count"] == 2
    assert data["edge_count"] == 1
    assert data["graph_status"] in ("persisted", "persisted_and_synced_to_neo4j", "persisted_neo4j_sync_failed")


async def test_persist_graph_nonexistent_assessment(v1_client):
    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/graph", json=_GRAPH_PAYLOAD
    )
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_get_graph_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/graph", json=_GRAPH_PAYLOAD)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {"auth_service", "user_db"}


async def test_get_graph_empty(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/graph")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["nodes"] == []
    assert data["edges"] == []


async def test_get_graph_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/graph")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_persist_graph_full_replace(v1_client):
    assessment_id = await _create_assessment(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/graph", json=_GRAPH_PAYLOAD)

    replacement = {
        "nodes": [{"id": "order_service", "name": "Order Service", "annual_cost": 20000.0}],
        "edges": [],
    }
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/graph", json=replacement)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/graph")
    data = response.json()["data"]
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["id"] == "order_service"
    assert data["edges"] == []
