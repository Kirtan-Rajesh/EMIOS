"""Business logic for the Auth module (register / login)."""

from __future__ import annotations

from typing import Tuple

from app.core.exceptions import DuplicateResourceException, UnauthorizedException
from app.core.security import create_access_token, hash_password, verify_password
from app.entities.user import User
from app.repositories.user_repository import UserRepository
from app.schemas_v1.auth import LoginRequest, RegisterRequest


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def register(self, payload: RegisterRequest) -> Tuple[User, str]:
        existing = await self.user_repo.get_by_email(payload.email)
        if existing is not None:
            raise DuplicateResourceException(f"Email '{payload.email}' is already registered.")
        user = User(email=payload.email, hashed_password=hash_password(payload.password))
        user = await self.user_repo.create(user)
        token = create_access_token(user.id)
        return user, token

    async def login(self, payload: LoginRequest) -> Tuple[User, str]:
        user = await self.user_repo.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedException("Invalid email or password.")
        token = create_access_token(user.id)
        return user, token
