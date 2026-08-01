"""Tests for the /api/v1 Auth module (register / login / me).

Uses the `v1_client` fixture from conftest.py, which wires each test to an
isolated in-memory SQLite database via a dependency override on `get_db`.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_register_happy_path(v1_client):
    payload = {"email": "Alice@Example.com", "password": "supersecret1"}
    response = await v1_client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["user"]["email"] == "alice@example.com"  # normalized to lowercase
    assert isinstance(data["user"]["user_id"], str) and data["user"]["user_id"]
    assert data["token_type"] == "bearer"
    assert isinstance(data["access_token"], str) and data["access_token"]


async def test_register_duplicate_email(v1_client):
    payload = {"email": "bob@example.com", "password": "supersecret1"}
    first = await v1_client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await v1_client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["success"] is False
    assert "message" in body


async def test_register_password_too_short(v1_client):
    payload = {"email": "carol@example.com", "password": "short"}
    response = await v1_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


async def test_register_invalid_email(v1_client):
    payload = {"email": "not-an-email", "password": "supersecret1"}
    response = await v1_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


async def test_login_happy_path(v1_client):
    await v1_client.post(
        "/api/v1/auth/register", json={"email": "dave@example.com", "password": "supersecret1"}
    )

    response = await v1_client.post(
        "/api/v1/auth/login", json={"email": "dave@example.com", "password": "supersecret1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["user"]["email"] == "dave@example.com"
    assert isinstance(body["data"]["access_token"], str) and body["data"]["access_token"]


async def test_login_wrong_password(v1_client):
    await v1_client.post(
        "/api/v1/auth/register", json={"email": "erin@example.com", "password": "supersecret1"}
    )

    response = await v1_client.post(
        "/api/v1/auth/login", json={"email": "erin@example.com", "password": "wrongpassword"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False


async def test_login_nonexistent_user(v1_client):
    response = await v1_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert response.status_code == 401
    assert response.json()["success"] is False


async def test_me_happy_path(v1_client):
    register_resp = await v1_client.post(
        "/api/v1/auth/register", json={"email": "frank@example.com", "password": "supersecret1"}
    )
    token = register_resp.json()["data"]["access_token"]

    response = await v1_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "frank@example.com"
    assert "created_at" in body["data"]


async def test_me_missing_token(v1_client):
    # v1_client also carries the session cookie set on this same fixture's
    # register() call (see conftest.py) - a real anonymous client would have
    # neither, so both need clearing to actually simulate "no credentials".
    del v1_client.headers["Authorization"]
    v1_client.cookies.clear()
    response = await v1_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["success"] is False


async def test_me_invalid_token(v1_client):
    # Same cookie-contamination note as test_me_missing_token above - without
    # clearing it, the still-valid session cookie from fixture setup would
    # authenticate the request regardless of the deliberately-invalid header.
    v1_client.cookies.clear()
    response = await v1_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    assert response.json()["success"] is False
