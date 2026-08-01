"""Async SQLAlchemy engine + session factory for the relational persistence layer.

Production/default target is PostgreSQL via ``asyncpg`` (see ``DATABASE_URL`` in
``app.core.config.Settings``). The ORM models in ``app/entities`` intentionally use
only portable, generic SQLAlchemy column types (String/Integer/Float/DateTime/Text/JSON)
so the exact same models also work unmodified against SQLite (``sqlite+aiosqlite``),
which is what the test-suite uses (see ``backend/tests/conftest.py``) since this
environment has no local Postgres available.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger("emios")


def get_db_url() -> str:
    """Returns the configured async SQLAlchemy database URL."""
    return settings.DATABASE_URL


# NOTE: create_async_engine() does not eagerly open a connection - it only builds
# a connection pool/dialect lazily. It is therefore safe to construct at import
# time even when no real Postgres instance is reachable (e.g. in this sandbox).
engine: AsyncEngine = create_async_engine(get_db_url(), echo=False, future=True, pool_pre_ping=True)

# expire_on_commit=False keeps ORM attributes accessible after commit, which the
# service layer relies on when building response schemas right after a write.
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
