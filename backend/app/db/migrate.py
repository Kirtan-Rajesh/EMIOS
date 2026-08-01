"""Applies the relational persistence layer's schema via real Alembic
migrations (alembic/versions/) - called once from main.py's startup hook.

This replaced an earlier `Base.metadata.create_all()` bootstrap (plus a
hand-rolled "add any column the model has that the live table doesn't" patch
written to paper over it): `create_all()` only creates tables that don't
exist yet, so a model field added after a table already exists - e.g.
`AgentRun.pipeline_metrics` - never reached any already-running database,
breaking every read of that table until someone noticed and manually altered
it. Versioned migrations are the actual fix: every schema change is a
reviewable file in `alembic/versions/`, and `alembic upgrade head` brings any
database - a teammate's, CI's, prod's - to the exact same, explicit state.
See `alembic/README.md` for the day-to-day workflow (creating a migration,
applying it).

One wrinkle, relevant only once per already-existing database: every
teammate's local Postgres was built by the old `create_all()` bootstrap
before this migration existed, so it already has every table the baseline
migration (`alembic/versions/..._baseline_schema.py`) would create, but no
`alembic_version` table recording that. Running `alembic upgrade head`
as-is against a database in that state would try to `CREATE TABLE` over
tables that already exist and fail outright. `run_migrations()` detects
exactly that one-time case - no `alembic_version` table, but a table the
baseline migration creates already present - and stamps the database at
`head` instead of replaying the DDL, so the first startup after pulling this
change "just works" for everyone on the team with no manual step. A brand
new database (nothing exists yet - a fresh clone, CI, a wiped local volume)
has neither table, so it takes the normal upgrade path and is actually built
from the migration files.

A second wrinkle on top of that: `create_all()` never alters a table that
already exists, so any model field added *after* a teammate's table was
first created (same failure mode the module docstring above already
describes for `AgentRun.pipeline_metrics`) is silently missing from their
live database even though the baseline migration - being generated from
today's models - declares it. Stamping to `head` only updates the version
bookkeeping, not the schema, so it can't close that gap by itself; a real
case of this hit `agent_runs.batch_id`/`final_result`/`pipeline_metrics`,
`assessment_reports.current_version`, and a missing `report_revisions`
table entirely. `_reconcile_schema_gaps()` runs after every startup (not
just the one-time stamp path - a database can carry this gap indefinitely
once `alembic_version` exists, since `upgrade head` is then a no-op forever
after) to patch exactly that: create any table `head` expects that isn't
there, and add (as nullable - existing rows have no value for it) any
column on an existing table that `head` expects but the live table lacks.
It's a no-op on a database that's actually already at head, so it's cheap
to always run.
"""
import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.concurrency import run_in_threadpool

from app.db.base import Base

logger = logging.getLogger("emios")

# backend/alembic.ini - independent of the caller's working directory.
_ALEMBIC_INI_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "alembic.ini")

# Any table the baseline migration creates works as the "does this database
# predate Alembic" sentinel - `assessments` is as good as any other.
_BOOTSTRAP_SENTINEL_TABLE = "assessments"


def _predates_alembic_adoption(sync_conn) -> bool:
    inspector = inspect(sync_conn)
    return not inspector.has_table("alembic_version") and inspector.has_table(_BOOTSTRAP_SENTINEL_TABLE)


def _reconcile_schema_gaps(sync_conn) -> None:
    inspector = inspect(sync_conn)
    live_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in live_tables:
            logger.warning("Schema reconcile: creating missing table '%s'.", table.name)
            table.create(bind=sync_conn)
            live_tables.add(table.name)
            continue
        live_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in live_columns:
                continue
            logger.warning("Schema reconcile: adding missing column '%s.%s'.", table.name, column.name)
            col_type = column.type.compile(dialect=sync_conn.dialect)
            sync_conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}')


async def run_migrations(engine: AsyncEngine) -> None:
    """Brings the database up to `head` - stamping instead of replaying DDL
    for a database that already has these tables from before Alembic was
    adopted (see module docstring). `command.upgrade`/`command.stamp` are
    synchronous and internally do their own `asyncio.run(...)` (the async
    template's env.py) - run_in_threadpool gives them a thread with no
    already-running event loop to conflict with, since this itself runs
    inside main.py's async startup hook."""
    async with engine.connect() as conn:
        needs_stamp_not_upgrade = await conn.run_sync(_predates_alembic_adoption)

    alembic_cfg = Config(_ALEMBIC_INI_PATH)

    if needs_stamp_not_upgrade:
        logger.warning(
            "Database has EMIOS tables but no alembic_version table - this predates "
            "Alembic adoption. Stamping at 'head' instead of replaying the baseline "
            "migration's DDL, since the live tables already match it."
        )
        await run_in_threadpool(command.stamp, alembic_cfg, "head")
    else:
        await run_in_threadpool(command.upgrade, alembic_cfg, "head")

    async with engine.begin() as conn:
        await conn.run_sync(_reconcile_schema_gaps)
