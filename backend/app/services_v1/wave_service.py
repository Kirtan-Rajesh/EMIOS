"""Business logic for the Migration Waves module."""

from __future__ import annotations

from typing import List, Sequence

from app.core.exceptions import DuplicateResourceException, ResourceNotFoundException
from app.entities.assessment import Assessment
from app.entities.wave import MigrationWave
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.wave_repository import WaveRepository
from app.schemas_v1.wave import WaveItem


class WaveService:
    def __init__(self, wave_repo: WaveRepository, assessment_repo: AssessmentRepository):
        self.wave_repo = wave_repo
        self.assessment_repo = assessment_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def create_waves(self, assessment_id: str, items: List[WaveItem]) -> List[MigrationWave]:
        await self._require_assessment(assessment_id)

        waves: List[MigrationWave] = []
        for item in items:
            existing = await self.wave_repo.get_by_assessment_and_number(assessment_id, item.wave_number)
            if existing is not None:
                raise DuplicateResourceException(
                    f"Wave number {item.wave_number} already exists for assessment '{assessment_id}'."
                )
            waves.append(
                MigrationWave(
                    assessment_id=assessment_id,
                    wave_number=item.wave_number,
                    components=item.components,
                    rationale=item.rationale,
                    risk_summary=item.risk_summary,
                )
            )
        # Committed as one transaction (not per-item) - see WaveRepository.
        # create_all()'s docstring for why: a collision partway through used
        # to leave the earlier items in this same batch permanently persisted
        # even though the request as a whole reports 409.
        return await self.wave_repo.create_all(assessment_id, waves)

    async def list_waves(self, assessment_id: str) -> Sequence[MigrationWave]:
        await self._require_assessment(assessment_id)
        return await self.wave_repo.list_for_assessment(assessment_id)
