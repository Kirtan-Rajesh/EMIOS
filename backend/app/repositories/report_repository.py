"""Data-access layer for the AssessmentReport entity (one row per assessment)
and its ReportRevision version history."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.report import AssessmentReport, ReportRevision


class ReportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_assessment(self, assessment_id: str) -> Optional[AssessmentReport]:
        result = await self.session.execute(
            select(AssessmentReport).where(AssessmentReport.assessment_id == assessment_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, assessment_id: str, values: Dict[str, Any]) -> AssessmentReport:
        """Creates or replaces the single report snapshot for an assessment."""
        existing = await self.get_by_assessment(assessment_id)
        if existing is None:
            report = AssessmentReport(assessment_id=assessment_id, **values)
            self.session.add(report)
            try:
                await self.session.commit()
            except IntegrityError:
                # Lost a race with a concurrent upsert for the same assessment_id
                # (unique constraint) - someone else's insert won first. Fall back
                # to updating their row instead of surfacing a raw 500.
                await self.session.rollback()
                existing = await self.get_by_assessment(assessment_id)
                for key, value in values.items():
                    setattr(existing, key, value)
                report = existing
                await self.session.commit()
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            report = existing
            await self.session.commit()
        await self.session.refresh(report)
        return report

    async def add_revision(self, report_id: str, values: Dict[str, Any]) -> ReportRevision:
        """Two concurrent revisions for the same report can both compute the
        same `values["version"]` (ReportService._persist_new_version reads
        `current_version` and adds 1, with no lock between that read and this
        write) - retried once with a freshly recomputed version number on a
        unique-constraint conflict (see ReportRevision.__table_args__) rather
        than surfacing a raw 500."""
        for attempt in range(2):
            revision = ReportRevision(report_id=report_id, **values)
            self.session.add(revision)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                if attempt == 1:
                    raise
                latest = await self.get_latest_version(report_id)
                values = {**values, "version": latest + 1}
                continue
            await self.session.refresh(revision)
            return revision
        raise AssertionError("unreachable")  # loop always returns or raises above

    async def get_latest_version(self, report_id: str) -> int:
        result = await self.session.execute(
            select(ReportRevision.version)
            .where(ReportRevision.report_id == report_id)
            .order_by(ReportRevision.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none() or 0

    async def list_revisions(self, report_id: str) -> List[ReportRevision]:
        result = await self.session.execute(
            select(ReportRevision).where(ReportRevision.report_id == report_id).order_by(ReportRevision.version.desc())
        )
        return list(result.scalars().all())

    async def get_revision(self, report_id: str, version: int) -> Optional[ReportRevision]:
        result = await self.session.execute(
            select(ReportRevision).where(
                ReportRevision.report_id == report_id, ReportRevision.version == version
            )
        )
        return result.scalar_one_or_none()
