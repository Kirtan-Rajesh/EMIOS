"""Tests for the /api/v1 Assessment Lifecycle module (create / get / patch status).

Uses the `v1_client` fixture from conftest.py, which wires each test to an
isolated in-memory SQLite database via a dependency override on `get_db`.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_assessment_happy_path(v1_client):
    payload = {
        "customer_name": "Acme Corp",
        "project_name": "Cloud Migration",
        "target_cloud": "AWS",
        "status": "created",
    }
    response = await v1_client.post("/api/v1/assessments", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert "message" in body
    data = body["data"]
    assert data["customer_name"] == "Acme Corp"
    assert data["project_name"] == "Cloud Migration"
    assert data["target_cloud"] == "AWS"
    assert data["status"] == "created"
    assert isinstance(data["assessment_id"], str) and data["assessment_id"]
    assert "created_at" in data
    assert "updated_at" in data


async def test_list_assessments_empty(v1_client):
    response = await v1_client.get("/api/v1/assessments")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == []


async def test_list_assessments_newest_first(v1_client):
    for name in ["First Corp", "Second Corp", "Third Corp"]:
        await v1_client.post(
            "/api/v1/assessments",
            json={"customer_name": name, "project_name": "Proj", "target_cloud": "AWS"},
        )

    response = await v1_client.get("/api/v1/assessments")
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 3
    assert [d["customer_name"] for d in data] == ["Third Corp", "Second Corp", "First Corp"]


async def test_create_assessment_default_status(v1_client):
    payload = {"customer_name": "Acme", "project_name": "Proj", "target_cloud": "Azure"}
    response = await v1_client.post("/api/v1/assessments", json=payload)

    assert response.status_code == 201
    assert response.json()["data"]["status"] == "created"


async def test_create_assessment_missing_required_field(v1_client):
    # customer_name is missing entirely.
    payload = {"project_name": "Proj", "target_cloud": "Azure"}
    response = await v1_client.post("/api/v1/assessments", json=payload)
    assert response.status_code == 422


async def test_create_assessment_wrong_type(v1_client):
    payload = {
        "customer_name": "Acme",
        "project_name": "Proj",
        "target_cloud": "Azure",
        "status": 123,  # status must be one of the allowed string literals
    }
    response = await v1_client.post("/api/v1/assessments", json=payload)
    assert response.status_code == 422


async def test_create_assessment_invalid_status_literal(v1_client):
    payload = {
        "customer_name": "Acme",
        "project_name": "Proj",
        "target_cloud": "Azure",
        "status": "bogus-status",
    }
    response = await v1_client.post("/api/v1/assessments", json=payload)
    assert response.status_code == 422


async def test_get_assessment_happy_path(v1_client):
    create_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "GCP"},
    )
    assessment_id = create_resp.json()["data"]["assessment_id"]

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["assessment_id"] == assessment_id
    assert body["data"]["target_cloud"] == "GCP"


async def test_get_assessment_not_found(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert "message" in body
    assert isinstance(body["errors"], list) and body["errors"]


async def test_update_assessment_status_happy_path(v1_client):
    create_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    assessment_id = create_resp.json()["data"]["assessment_id"]

    response = await v1_client.patch(
        f"/api/v1/assessments/{assessment_id}/status", json={"status": "analyzing"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "analyzing"
    assert body["data"]["assessment_id"] == assessment_id


async def test_update_assessment_status_not_found(v1_client):
    response = await v1_client.patch(
        "/api/v1/assessments/does-not-exist/status", json={"status": "analyzing"}
    )
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_update_assessment_status_invalid_value(v1_client):
    create_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    assessment_id = create_resp.json()["data"]["assessment_id"]

    response = await v1_client.patch(
        f"/api/v1/assessments/{assessment_id}/status", json={"status": "not-a-real-status"}
    )
    assert response.status_code == 422


async def test_update_assessment_status_missing_field(v1_client):
    create_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    assessment_id = create_resp.json()["data"]["assessment_id"]

    response = await v1_client.patch(f"/api/v1/assessments/{assessment_id}/status", json={})
    assert response.status_code == 422


async def test_list_assessments_requires_auth(v1_client):
    # v1_client also carries the session cookie set on this same fixture's
    # register() call (see conftest.py) - a real anonymous client would have
    # neither, so both need clearing to actually simulate "no credentials".
    del v1_client.headers["Authorization"]
    v1_client.cookies.clear()
    response = await v1_client.get("/api/v1/assessments")
    assert response.status_code == 401


async def test_create_assessment_requires_auth(v1_client):
    del v1_client.headers["Authorization"]
    v1_client.cookies.clear()
    response = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    assert response.status_code == 401


async def test_list_assessments_does_not_leak_other_users(v1_client, make_authenticated_client):
    # v1_client (the default test user) creates one assessment.
    await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Owner Corp", "project_name": "Owner Proj", "target_cloud": "AWS"},
    )

    async with make_authenticated_client("other-user@example.com") as other_client:
        # A brand new user creates their own, separate assessment.
        await other_client.post(
            "/api/v1/assessments",
            json={"customer_name": "Other Corp", "project_name": "Other Proj", "target_cloud": "Azure"},
        )

        other_list = await other_client.get("/api/v1/assessments")
        assert other_list.status_code == 200
        other_names = [a["customer_name"] for a in other_list.json()["data"]]
        assert other_names == ["Other Corp"]

    owner_list = await v1_client.get("/api/v1/assessments")
    owner_names = [a["customer_name"] for a in owner_list.json()["data"]]
    assert owner_names == ["Owner Corp"]


async def test_get_assessment_not_found_for_other_user(v1_client, make_authenticated_client):
    create_resp = await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Owner Corp", "project_name": "Owner Proj", "target_cloud": "AWS"},
    )
    assessment_id = create_resp.json()["data"]["assessment_id"]

    async with make_authenticated_client("other-user-2@example.com") as other_client:
        response = await other_client.get(f"/api/v1/assessments/{assessment_id}")
        assert response.status_code == 404


async def test_dashboard_summary_scoped_per_user(v1_client, make_authenticated_client):
    await v1_client.post(
        "/api/v1/assessments",
        json={"customer_name": "Owner Corp", "project_name": "Owner Proj", "target_cloud": "AWS"},
    )

    async with make_authenticated_client("other-user-3@example.com") as other_client:
        summary = await other_client.get("/api/v1/dashboard/summary")
        assert summary.status_code == 200
        assert summary.json()["data"]["total_assessments"] == 0

    owner_summary = await v1_client.get("/api/v1/dashboard/summary")
    assert owner_summary.json()["data"]["total_assessments"] == 1
