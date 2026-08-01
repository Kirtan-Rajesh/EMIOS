"""Data-access layer for the User entity."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateResourceException
from app.entities.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user: User) -> User:
        """AuthService.register() already checks get_by_email() before calling
        this, but that check-then-insert isn't atomic - two concurrent
        registrations for the same email can both pass that check before
        either commits. User.email's unique constraint catches what the
        check missed; without this handling, the loser's insert would raise
        an unhandled IntegrityError -> raw 500 instead of the intended 409."""
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise DuplicateResourceException(f"Email '{user.email}' is already registered.")
        await self.session.refresh(user)
        return user

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
