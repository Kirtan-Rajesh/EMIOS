"""Tests for the /api/v1 Migration Waves module (batch-store planner output / list).

Covers: happy path (multi-wave batch), validation errors, 404 for a nonexistent
assessment, and 409 for a duplicate wave_number within the same assessment.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


async def test_create_waves_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)
    payload = {
        "waves": [
            {
                "wave_number": 1,
                "components": ["auth_service", "user_db"],
                "rationale": "Low-risk, few dependencies.",
                "risk_summary": {"level": "low", "score": 0.2},
            },
            {
                "wave_number": 2,
                "components": ["order_service"],
                "rationale": "Depends on wave 1 completing first.",
                "risk_summary": "medium risk",
            },
        ]
    }

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert len(data) == 2
    assert data[0]["wave_number"] == 1
    assert data[0]["components"] == ["auth_service", "user_db"]
    assert data[0]["risk_summary"] == {"level": "low", "score": 0.2}
    assert data[1]["wave_number"] == 2
    assert data[1]["risk_summary"] == "medium risk"
    for wave in data:
        assert wave["assessment_id"] == assessment_id
        assert isinstance(wave["wave_id"], str) and wave["wave_id"]
        assert "created_at" in wave


async def test_create_waves_missing_required_field(v1_client):
    assessment_id = await _create_assessment(v1_client)
    # rationale is missing.
    payload = {"waves": [{"wave_number": 1, "components": ["a"], "risk_summary": "x"}]}

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)
    assert response.status_code == 422


async def test_create_waves_wrong_type(v1_client):
    assessment_id = await _create_assessment(v1_client)
    payload = {
        "waves": [
            {
                "wave_number": "not-a-number",
                "components": ["a"],
                "rationale": "r",
                "risk_summary": "x",
            }
        ]
    }

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)
    assert response.status_code == 422


async def test_create_waves_empty_batch_rejected(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json={"waves": []})
    assert response.status_code == 422


async def test_create_waves_nonexistent_assessment(v1_client):
    payload = {"waves": [{"wave_number": 1, "components": ["a"], "rationale": "r", "risk_summary": "x"}]}

    response = await v1_client.post("/api/v1/assessments/does-not-exist/waves", json=payload)

    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_create_waves_duplicate_wave_number(v1_client):
    assessment_id = await _create_assessment(v1_client)
    payload = {"waves": [{"wave_number": 1, "components": ["a"], "rationale": "r", "risk_summary": "x"}]}

    first = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)
    assert first.status_code == 201

    second = await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["success"] is False
    assert "message" in body
    assert "errors" in body


async def test_list_waves_happy_path(v1_client):
    assessment_id = await _create_assessment(v1_client)
    payload = {"waves": [{"wave_number": 1, "components": ["a"], "rationale": "r", "risk_summary": "x"}]}
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/waves", json=payload)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/waves")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["wave_number"] == 1


async def test_list_waves_empty(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/waves")

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_list_waves_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/waves")

    assert response.status_code == 404
    assert response.json()["success"] is False
