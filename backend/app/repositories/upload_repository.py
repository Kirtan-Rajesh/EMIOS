"""Data-access layer for the AssessmentUpload entity."""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.upload import AssessmentUpload


class UploadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, upload: AssessmentUpload) -> AssessmentUpload:
        self.session.add(upload)
        await self.session.commit()
        await self.session.refresh(upload)
        return upload

    async def list_for_assessment(self, assessment_id: str) -> Sequence[AssessmentUpload]:
        result = await self.session.execute(
            select(AssessmentUpload)
            .where(AssessmentUpload.assessment_id == assessment_id)
            .order_by(AssessmentUpload.uploaded_at.desc(), AssessmentUpload.id.desc())
        )
        return result.scalars().all()

    async def update_status(self, upload: AssessmentUpload, status: str) -> AssessmentUpload:
        upload.status = status
        await self.session.commit()
        await self.session.refresh(upload)
        return upload
