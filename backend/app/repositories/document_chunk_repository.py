"""Data-access layer for the DocumentChunk entity."""

from __future__ import annotations

from typing import Dict, List, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.entities.document_chunk import DocumentChunk


class DocumentChunkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bulk_create(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        self.session.add_all(chunks)
        await self.session.commit()
        for chunk in chunks:
            await self.session.refresh(chunk)
        return chunks

    async def list_for_upload(self, upload_id: str) -> Sequence[DocumentChunk]:
        result = await self.session.execute(
            select(DocumentChunk).where(DocumentChunk.upload_id == upload_id)
        )
        return result.scalars().all()

    async def count_for_upload(self, upload_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.upload_id == upload_id)
        )
        return int(result.scalar_one())

    async def count_for_uploads(self, upload_ids: Sequence[str]) -> Dict[str, int]:
        """Same as count_for_upload but for many uploads in one query - callers
        listing every upload for an assessment (UploadService.list_uploads)
        must not fire one COUNT query per upload (an N+1 that scales with how
        many documents have ever been uploaded, unrelated to what's being
        rendered right now). Ids with zero chunks are simply absent from the
        result; callers should default missing keys to 0."""
        if not upload_ids:
            return {}
        result = await self.session.execute(
            select(DocumentChunk.upload_id, func.count())
            .where(DocumentChunk.upload_id.in_(upload_ids))
            .group_by(DocumentChunk.upload_id)
        )
        return {upload_id: count for upload_id, count in result.all()}

    async def delete_for_upload(self, upload_id: str) -> None:
        await self.session.execute(delete(DocumentChunk).where(DocumentChunk.upload_id == upload_id))
        await self.session.commit()
