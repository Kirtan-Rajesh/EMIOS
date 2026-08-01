"""Pydantic v2 request/response schemas for the Auth module.

JSON bodies (not OAuth2 form) - consistent with the rest of the v1 API being JSON.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValueError("Invalid email address.")
        return v

    @field_validator("password")
    @classmethod
    def _check_bcrypt_byte_limit(cls, v: str) -> str:
        # bcrypt (app/core/security.py) hard-rejects passwords over 72 bytes rather
        # than truncating - reject here with a clean 422 instead of a 500 from
        # inside hash_password. max_length=128 above counts characters, not bytes,
        # so a 73-128 char password can still exceed 72 bytes (immediately for any
        # multi-byte character, or beyond 72 for plain ASCII).
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes when UTF-8 encoded.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AuthUser(BaseModel):
    user_id: str
    email: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    created_at: datetime
