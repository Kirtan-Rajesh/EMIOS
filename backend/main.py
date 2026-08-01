import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.db import init_db, close_db
from app.core.storage import init_storage
from app.core.logging_config import setup_logging
from app.api.endpoints import router as api_router
from app.api.v1 import router as v1_router

# Importing app.entities registers all ORM models (Assessment, AssessmentUpload,
# MigrationWave) on the shared app.db.base.Base metadata - alembic/env.py needs
# the same import for autogenerate, but the startup hook below only needs the
# engine to actually run the migrations in alembic/versions/.
import app.entities  # noqa: F401
from app.db.session import engine as db_engine
from app.db.migrate import run_migrations

setup_logging()

app = FastAPI(
    title="EMIOS API - Enterprise Migration Intelligence Operating System",
    description="Backend API powering the digital twin visualization, cascading risk simulator, and multi-agent migration planner.",
    version="1.0.0"
)

# Set up CORS middleware. The browser client authenticates via an httpOnly
# cookie (app/api/v1/auth.py sets it on login/register), so every request from
# it needs `credentials: "include"` - and allow_origins=["*"] combined with
# allow_credentials=True is invalid per the Fetch/CORS spec (a compliant
# browser refuses to reflect "*" once credentials are requested), so
# allow_origins must be an explicit list once credentials are on. Direct API/
# tooling access (curl, tests) still works unauthenticated-cookie-wise via the
# Authorization header fallback in app/dependencies/auth.py, which CORS
# doesn't gate at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
import logging

logger = logging.getLogger("emios")

@app.middleware("http")
async def log_latency_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Request: {request.method} {request.url.path} | "
        f"Status: {response.status_code} | "
        f"Latency: {duration:.4f}s"
    )
    return response

from fastapi.responses import JSONResponse
from app.core.exceptions import (
    EMIOSException,
    ResourceNotFoundException,
    DuplicateResourceException,
    UnauthorizedException,
    BadRequestException,
)

@app.exception_handler(EMIOSException)
async def emios_exception_handler(request, exc: EMIOSException):
    # Legacy /api/* error shape - left exactly as-is so existing behavior/tests
    # for the unversioned API surface are unaffected.
    logger.warning(f"{request.method} {request.url.path} -> {exc.error_code}: {exc.message}")
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "error_code": exc.error_code,
            "message": exc.message
        }
    )

# More specific handlers for the /api/v1 persistence-layer exceptions. FastAPI/Starlette
# picks the most specific registered handler by walking the exception's MRO, so these take
# precedence over the EMIOSException handler above for these two subclasses without touching
# it - existing /api/* exceptions (InvalidIngestionException, SimulationException, etc.) are
# untouched and keep returning the legacy shape/status via the handler above.
@app.exception_handler(ResourceNotFoundException)
async def resource_not_found_handler(request, exc: ResourceNotFoundException):
    logger.warning(f"{request.method} {request.url.path} -> 404: {exc.message}")
    return JSONResponse(
        status_code=404,
        content={"success": False, "message": exc.message, "errors": [exc.message]}
    )

@app.exception_handler(DuplicateResourceException)
async def duplicate_resource_handler(request, exc: DuplicateResourceException):
    logger.warning(f"{request.method} {request.url.path} -> 409: {exc.message}")
    return JSONResponse(
        status_code=409,
        content={"success": False, "message": exc.message, "errors": [exc.message]}
    )

@app.exception_handler(UnauthorizedException)
async def unauthorized_handler(request, exc: UnauthorizedException):
    logger.warning(f"{request.method} {request.url.path} -> 401: {exc.message}")
    return JSONResponse(
        status_code=401,
        content={"success": False, "message": exc.message, "errors": [exc.message]}
    )

@app.exception_handler(BadRequestException)
async def bad_request_handler(request, exc: BadRequestException):
    logger.warning(f"{request.method} {request.url.path} -> 400: {exc.message}")
    return JSONResponse(
        status_code=400,
        content={"success": False, "message": exc.message, "errors": [exc.message]}
    )

# Catch-all for anything not raised as one of the app's own exception types above
# (a genuine bug, a third-party library error, etc.). Without this, an unhandled
# exception falls through to Starlette's bare default handler - no app-level log
# line, and for a normal (non-streaming) request, an opaque plain-text 500 with
# no JSON body the frontend's error handling can read a message out of.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    # Full exception detail (message, type, traceback) goes to the server-side
    # log only via logger.exception() - never into the response body. A raw
    # DB/Neo4j/Qdrant/boto3 error's str(exc) can contain connection strings,
    # internal file paths, or SQL fragments; echoing it back to whoever
    # triggered the error (not necessarily someone who should see internals)
    # was an information-disclosure gap.
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "An unexpected server error occurred.", "errors": []}
    )

_DEFAULT_JWT_SECRET = "emios-dev-secret-change-me-in-production"


@app.on_event("startup")
async def startup_event():
    # docker-compose.prod.yml already requires JWT_SECRET_KEY to be set via
    # ${JWT_SECRET_KEY:?...} (fails to start if missing) - but that's only
    # protection for that one deploy path. Running the app any other way
    # (bare uvicorn/python main.py, a future deploy script) with no .env
    # override silently ships the public, source-controlled default secret,
    # letting anyone forge a valid JWT. Loud startup warning rather than a
    # hard failure, since local/dev intentionally relies on this default and
    # should keep working unmodified.
    if settings.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET:
        logger.warning(
            "JWT_SECRET_KEY is still the public, source-controlled default value - "
            "anyone who has read this codebase can forge valid session tokens. Set a "
            "real secret via JWT_SECRET_KEY in backend/.env before this is reachable "
            "by anyone other than you."
        )

    init_db()
    init_storage()

    # Bring the relational persistence layer's schema up to `head` via the
    # versioned migrations in alembic/versions/ (see app/db/migrate.py's
    # docstring for the one-time bootstrap this does for a database that
    # predates Alembic adoption). Wrapped in try/except (matching the
    # try-real-DB/fall-back-gracefully house style used by init_db() above)
    # so the app still boots - and the /api/* surface stays fully usable -
    # even when no Postgres instance is reachable (e.g. local dev without Docker).
    try:
        await run_migrations(db_engine)
        logger.info("Relational persistence tables migrated to head successfully.")
    except Exception as e:
        logger.warning(
            f"Could not migrate relational persistence tables at startup: {e}. "
            f"/api/v1 endpoints will fail until a reachable DATABASE_URL is configured."
        )

@app.on_event("shutdown")
async def shutdown_event():
    close_db()

    # Langfuse batches trace/generation events on a background thread; flush
    # here so anything queued from the last request(s) isn't dropped on exit.
    from app.core import observability
    observability.flush()

# Register API routes
app.include_router(api_router, prefix="/api")
app.include_router(v1_router, prefix="/api/v1")

# Serve the built React SPA (frontend/dist - built via `npm run build`, not the
# frontend/src sources directly, which browsers can't execute unbuilt). Same
# "unconditional, crashes if missing" contract as before: a missing dist/ means
# the frontend build step was skipped, and that should fail loudly rather than
# silently serve nothing.
#
# Plain StaticFiles(html=True) mounted at "/" only serves index.html for "/"
# itself - it 404s a direct browser navigation/refresh on a client-side route
# like /dashboard or /assessments/{id}/plan, since no such file exists in dist/.
# The catch-all route below serves any real built file (JS/CSS/favicon) as-is,
# and falls back to index.html for everything else so React Router can resolve
# the route client-side - the standard SPA-on-a-static-host pattern.
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

frontend_dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if not os.path.isdir(frontend_dist_dir):
    raise RuntimeError(
        f"Frontend build output not found at '{frontend_dist_dir}'. Run `npm run build` in "
        f"frontend/ (or the Docker image's frontend-builder stage) before starting the backend."
    )

app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist_dir, "assets")), name="frontend-assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    candidate = os.path.join(frontend_dist_dir, full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)
    return FileResponse(os.path.join(frontend_dist_dir, "index.html"))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
