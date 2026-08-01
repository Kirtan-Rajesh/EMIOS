"""FastAPI dependencies for authentication and per-assessment authorization.

``get_current_user`` resolves the caller from the session cookie (browser client)
or a bearer JWT (direct API/tooling) - see app/api/v1/auth.py's module docstring
for why both are accepted. ``require_assessment_owner``
builds on it to gate every ``/assessments/{assessment_id}/...`` sub-resource route
(uploads, graph, simulate, agent-runs, reports, chat, waves, discovery) behind both
authentication AND ownership - see its own docstring below for why this exists as a
shared dependency rather than being threaded through each service.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundException, UnauthorizedException
from app.core.security import decode_access_token
from app.dependencies.db import get_db
from app.entities.user import User
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.user_repository import UserRepository

# Session cookie name the browser client authenticates with - set/cleared by
# app/api/v1/auth.py's register/login/logout, read here. Named distinctly
# (not "token"/"session") to avoid colliding with any other cookie a future
# integration might set on the same origin.
AUTH_COOKIE_NAME = "emios_session"

# auto_error=False so a missing header raises our own UnauthorizedException (401,
# {"success": false, ...} envelope) instead of FastAPI's default 403 HTTPException.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Cookie first (the browser client's path - see auth.py's module docstring),
    # falling back to the Authorization header for direct API/tooling callers
    # (curl, tests, CI scripts) that were never going to send a cookie anyway.
    token = request.cookies.get(AUTH_COOKIE_NAME) or (credentials.credentials if credentials else None)
    if not token:
        raise UnauthorizedException("Missing session cookie or bearer token.")

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("Session token has expired.")
    except jwt.PyJWTError:
        raise UnauthorizedException("Invalid session token.")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException("Invalid session token.")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise UnauthorizedException("User no longer exists.")
    return user


async def require_assessment_owner(
    assessment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Shared authorization guard for every ``/assessments/{assessment_id}/...``
    sub-resource route (uploads, graph, simulate, agent-runs, reports, chat,
    waves, discovery).

    Until now, none of those routers depended on authentication at all - only
    the Assessment Lifecycle routes (app/api/v1/assessments.py) did, and each
    sub-resource *service* only confirmed the assessment existed (unscoped
    ``AssessmentRepository.get_by_id``), explicitly deferring ownership
    enforcement to "the Assessment Lifecycle routes" per that repository's own
    docstring. But those sub-resource routes are reachable directly - a caller
    never has to go through the lifecycle routes at all - so in practice
    ownership was never actually enforced on any of them: anyone (including a
    fully unauthenticated request) who obtained an assessment_id (a shared
    link, browser history, a support session) could read or overwrite that
    assessment's documents, graph, chat, simulation, and report.

    Add this as a dependency on every route under ``{assessment_id}`` instead
    of threading a `user_id` parameter through every service method - FastAPI
    resolves `assessment_id` from the path automatically by parameter name,
    dependencies with the same callable are cached per-request (so this adds
    no extra DB round trip beyond the one it needs), and it keeps the
    authorization check in exactly one place rather than duplicated across
    eight services. Raises 404 (not 403) when the assessment doesn't exist OR
    isn't owned by the caller - same shape AssessmentService.get_assessment()
    already uses - so a caller probing someone else's assessment_id can't use
    the response to distinguish "doesn't exist" from "exists but isn't yours".
    """
    assessment = await AssessmentRepository(db).get_by_id_for_user(assessment_id, current_user.id)
    if assessment is None:
        raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
