"""Data-access layer for the MigrationWave entity."""

from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateResourceException
from app.entities.wave import MigrationWave


class WaveRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_all(self, assessment_id: str, waves: List[MigrationWave]) -> List[MigrationWave]:
        """Commits an entire batch of waves in one transaction - WaveService.
        create_waves() already checks get_by_assessment_and_number() for each
        item before calling this, but that check-then-insert isn't atomic:
        two concurrent requests posting the same wave_number can both pass
        that check before either commits, and committing per-item (the
        previous behavior) meant a collision on item 3 of a 5-item batch left
        items 1-2 permanently persisted even though the whole request reports
        409. Committing once for the whole batch means a collision leaves
        nothing behind. The uq_migration_wave_assessment_number constraint
        (app/entities/wave.py) catches what the pre-check missed; without
        this handling, that would surface as a raw 500 instead of a 409."""
        for wave in waves:
            self.session.add(wave)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise DuplicateResourceException(
                f"One or more of these wave numbers already exist for assessment '{assessment_id}' "
                f"(a concurrent request may have just created one)."
            )
        for wave in waves:
            await self.session.refresh(wave)
        return waves

    async def list_for_assessment(self, assessment_id: str) -> Sequence[MigrationWave]:
        result = await self.session.execute(
            select(MigrationWave)
            .where(MigrationWave.assessment_id == assessment_id)
            .order_by(MigrationWave.wave_number.asc())
        )
        return result.scalars().all()

    async def get_by_assessment_and_number(
        self, assessment_id: str, wave_number: int
    ) -> Optional[MigrationWave]:
        result = await self.session.execute(
            select(MigrationWave).where(
                MigrationWave.assessment_id == assessment_id,
                MigrationWave.wave_number == wave_number,
            )
        )
        return result.scalar_one_or_none()
