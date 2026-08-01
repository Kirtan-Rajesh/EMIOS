"""Password hashing (bcrypt) and JWT (PyJWT) helpers for the /api/v1 auth module.

Uses the ``bcrypt`` package directly rather than ``passlib`` - passlib's bcrypt
backend probes ``bcrypt.__about__.__version__``, which bcrypt>=4.1 no longer
ships, breaking password verification at import/use time. Calling
``bcrypt.hashpw``/``bcrypt.checkpw`` directly sidesteps that compatibility break
entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decodes and verifies a JWT. Raises jwt.PyJWTError subclasses (ExpiredSignatureError,
    InvalidSignatureError, DecodeError, ...) on any invalid/expired token - callers
    (see app/dependencies/auth.py) are responsible for mapping those to UnauthorizedException."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
