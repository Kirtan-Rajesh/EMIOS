"""Auth routes: register / login / logout / current-user profile.

The Assessment Lifecycle + Dashboard Summary routes (app/api/v1/assessments.py,
app/api/v1/dashboard.py) require auth directly via `get_current_user` and scope
data by owner (created_by). Every other assessment sub-resource route
(uploads/waves/graph/simulate/agent-runs/reports/chat/discovery) is gated the
same way, but indirectly, via `app.dependencies.auth.require_assessment_owner`
- see that function's docstring for why it's a separate shared dependency
rather than each service re-implementing the same ownership check.

register/login set an httpOnly session cookie (see _set_auth_cookie) - the
browser client (frontend/src/lib/api.ts) authenticates via that cookie alone
and never touches the token in JS, closing the localStorage/XSS-exfiltration
vector that existed before. The response body still also carries
`access_token` for direct API/tooling use (curl, backend/tests/conftest.py's
fixtures, CI scripts) via the `Authorization: Bearer` header fallback in
app/dependencies/auth.py's get_current_user - both paths are accepted so
neither breaks the other.
"""

from fastapi import APIRouter, Depends, Response, status

from app.core.config import settings
from app.dependencies.auth import AUTH_COOKIE_NAME, get_current_user
from app.dependencies.services import get_auth_service
from app.entities.user import User
from app.schemas_v1.auth import AuthUser, CurrentUserResponse, LoginRequest, RegisterRequest
from app.schemas_v1.envelope import success_envelope
from app.services_v1.auth_service import AuthService

router = APIRouter(tags=["Auth"])


def _to_auth_response(user: User, token: str) -> dict:
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": AuthUser(user_id=user.id, email=user.email).model_dump(mode="json"),
    }


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        path="/",
    )


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, response: Response, service: AuthService = Depends(get_auth_service)):
    """Registers a new user, sets the session cookie, and returns a bearer
    token in the body too (see module docstring). 409s on duplicate email."""
    user, token = await service.register(payload)
    _set_auth_cookie(response, token)
    return success_envelope(_to_auth_response(user, token), message="User registered successfully.")


@router.post("/auth/login")
async def login(payload: LoginRequest, response: Response, service: AuthService = Depends(get_auth_service)):
    """Authenticates a user, sets the session cookie, and returns a bearer
    token in the body too (see module docstring). 401s on bad credentials."""
    user, token = await service.login(payload)
    _set_auth_cookie(response, token)
    return success_envelope(_to_auth_response(user, token), message="Login successful.")


@router.post("/auth/logout")
async def logout(response: Response):
    """Clears the session cookie - the JWT itself is stateless and stays valid
    until it expires, this only ends the browser's session. No auth dependency:
    clearing a cookie that's already missing/expired is harmless, and a client
    that's already logged out shouldn't get a 401 just for calling this."""
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return success_envelope(None, message="Logged out successfully.")


@router.get("/auth/me")
async def me(current_user: User = Depends(get_current_user)):
    """Returns the authenticated user's profile. 401s without a valid session
    (cookie or bearer token)."""
    response = CurrentUserResponse(
        user_id=current_user.id, email=current_user.email, created_at=current_user.created_at
    )
    return success_envelope(response.model_dump(mode="json"), message="Current user retrieved successfully.")
