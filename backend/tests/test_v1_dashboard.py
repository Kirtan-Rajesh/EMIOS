"""Tests for the /api/v1 Dashboard Summary module.

Confirms the summary is computed from persisted (relational) assessment records
rather than any in-memory state, and that its counts stay consistent as
assessments are created and transition status.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_dashboard_summary_empty(v1_client):
    response = await v1_client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total_assessments"] == 0
    assert data["completed_assessments"] == 0
    assert data["active_assessments"] == 0
    assert data["latest_assessment_id"] is None


async def test_dashboard_summary_with_mixed_assessments(v1_client):
    # One assessment left "analyzing" (active).
    await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "A", "project_name": "P1", "target_cloud": "AWS", "status": "analyzing"},
    )

    # One assessment transitioned to "complete".
    completed_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "B", "project_name": "P2", "target_cloud": "Azure"},
    )
    completed_id = completed_resp.json()["data"]["assessment_id"]
    await v1_client.patch(f"/api/v1/assessments/{completed_id}/status", json={"status": "complete"})

    # One assessment transitioned to "failed" - and is the most recently created.
    failed_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "C", "project_name": "P3", "target_cloud": "GCP"},
    )
    failed_id = failed_resp.json()["data"]["assessment_id"]
    await v1_client.patch(f"/api/v1/assessments/{failed_id}/status", json={"status": "failed"})

    response = await v1_client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_assessments"] == 3
    assert data["completed_assessments"] == 1
    # active = total - completed - failed = 3 - 1 - 1 = 1 (the "analyzing" one)
    assert data["active_assessments"] == 1
    assert data["latest_assessment_id"] == failed_id


async def test_dashboard_summary_response_envelope_shape(v1_client):
    response = await v1_client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"success", "message", "data"}
    assert set(body["data"].keys()) == {
        "total_assessments",
        "completed_assessments",
        "active_assessments",
        "latest_assessment_id",
    }
