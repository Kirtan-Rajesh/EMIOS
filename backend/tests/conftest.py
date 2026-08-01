"""Shared test setup for EMIOS.

The project is intentionally runnable from the repository root.  Keeping the
backend directory on ``sys.path`` here makes direct ``pytest`` runs and CI
runs behave the same way.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# /api/v1 persistence-layer test fixtures.
#
# These are additive to the sys.path setup above (which must stay intact for
# the legacy /api/* tests). They give the new SQLAlchemy-backed /api/v1 tests
# an isolated, in-memory SQLite database per test, via a dependency override
# on `get_db` - the production app (main.py / app/db/session.py) still targets
# PostgreSQL by default and is never touched by these fixtures.
# ---------------------------------------------------------------------------

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.dependencies.db import get_db

# Importing app.entities registers Assessment/AssessmentUpload/MigrationWave on
# Base.metadata - required before create_all() below can create every table.
import app.entities  # noqa: F401

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(autouse=True)
async def _isolated_local_storage(tmp_path, monkeypatch):
    """Redirects app.core.storage's local-disk fallback to a per-test temp dir.

    There's no live-infra test override for object storage the way get_db has
    one for the database (see v1_client below) - without this, every test run
    would write real files under ./storage_fallback in the repo root (no AWS
    credentials are configured in this environment, so uploads always hit the
    local-disk fallback path)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path / "storage_fallback"))


@pytest.fixture(autouse=True)
def _no_real_llm_credentials(monkeypatch, tmp_path):
    """Tests must never make real, paid, network-dependent calls to
    Bedrock/OpenAI/Gemini/Azure OpenAI, no matter what a developer has
    configured in their real backend/.env for manual/local use (see README's
    "tests never require live infra" convention) - this blanks every provider
    credential for the duration of each test so app.core.llm_provider /
    app.core.embeddings always fall through to their deterministic fallbacks.
    reset_embedding_provider_cache()/reset_llm_provider_cache() undo the
    memoization from any prior test so the blanked settings actually take
    effect.

    Blanking Settings alone is NOT sufficient: app.core.config.get_boto3_client()
    only passes explicit aws_access_key_id/aws_secret_access_key kwargs when
    Settings has them - when blank (as above), it still calls boto3.client(...),
    which then falls through to boto3's OWN default credential chain (env vars,
    ~/.aws/credentials, an attached EC2/ECS instance role) completely
    independently of Settings. A real ~/.aws/credentials file on a developer's
    machine (or a real instance role in CI) would otherwise let every test that
    touches embeddings/LLM extraction silently make real, paid Bedrock calls
    despite the blanking above - confirmed this actually happens: a local
    ~/.aws/credentials predating any of this test work let LlmPromptExtractor
    return a real (non-fallback) result during test development. Force every
    remaining layer of that chain to a dead end too, so boto3 always ends up
    with zero usable credentials and the deterministic fallback path is
    guaranteed to fire, regardless of what's on the machine running the suite."""
    from app.core.config import settings
    from app.core.embeddings import reset_embedding_provider_cache
    from app.core.llm_provider import reset_llm_provider_cache

    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", None)

    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    # Point boto3's shared-credentials/config file lookup at paths that don't
    # exist, and disable the EC2/ECS instance-metadata credential lookup -
    # covers every remaining source in boto3's default credential chain.
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "nonexistent_aws_credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "nonexistent_aws_config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    reset_embedding_provider_cache()
    reset_llm_provider_cache()
    yield
    reset_embedding_provider_cache()
    reset_llm_provider_cache()


@pytest_asyncio.fixture
async def db_engine():
    """A fresh in-memory SQLite async engine, schema created, per test function.

    StaticPool + check_same_thread=False makes every connection checked out of
    this engine share the same underlying in-memory SQLite database, which is
    required since :memory: SQLite databases are otherwise per-connection.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def v1_client(db_engine):
    """Async HTTP client for exercising /api/v1 routes against the isolated test DB.

    Deliberately uses httpx.AsyncClient + ASGITransport rather than FastAPI's sync
    TestClient: TestClient dispatches each request from a separate thread with its
    own event loop, which breaks aiosqlite connections/sessions that are bound to
    the event loop they were created on. Running the test, the ASGI app, and the
    async SQLAlchemy session all on the same pytest-asyncio event loop (via
    asyncio_mode = auto in pytest.ini) avoids that entirely.

    Carries a default logged-in user's bearer token by default (the Assessment
    Lifecycle + Dashboard routes require auth so they can scope data per-owner -
    see app/api/v1/assessments.py) so every existing test keeps working as "one
    signed-in user" without each test file wiring up auth itself. Tests that
    specifically need a *second*, distinct user (e.g. cross-user isolation) use
    make_authenticated_client below instead.
    """
    from main import app

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            register_resp = await client.post(
                "/api/v1/auth/register",
                json={"email": "default-test-user@example.com", "password": "supersecret1"},
            )
            token = register_resp.json()["data"]["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def make_authenticated_client(db_engine):
    """Factory for a *second* (or third, ...) independently-authenticated async
    client against the same isolated test DB as v1_client - for tests that need
    to verify behavior differs across two distinct users (e.g. assessment list
    isolation), since v1_client alone only ever represents one signed-in user.
    """
    from main import app

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)

    @asynccontextmanager
    async def _factory(email: str):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            register_resp = await client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": "supersecret1"},
            )
            token = register_resp.json()["data"]["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            yield client

    try:
        yield _factory
    finally:
        app.dependency_overrides.pop(get_db, None)
