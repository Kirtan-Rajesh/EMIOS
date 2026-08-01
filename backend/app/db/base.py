"""SQLAlchemy declarative base for the relational persistence layer.

All ORM entities under ``app/entities`` must inherit from this ``Base`` so
they share a single ``MetaData`` registry, which is what lets the startup
hook in ``main.py`` (and the test fixtures in ``backend/tests/conftest.py``)
call ``Base.metadata.create_all`` to bootstrap tables without Alembic.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all relational (SQLAlchemy) entities."""
    pass
