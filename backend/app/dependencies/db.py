"""FastAPI dependency that yields an async SQLAlchemy session per request.

Tests override this dependency (see ``backend/tests/conftest.py``) to point at an
in-memory SQLite engine instead of the production Postgres engine, without
touching any router/service/repository code.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
