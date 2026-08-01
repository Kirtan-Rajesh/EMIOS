"""RAG vector store: embeds and retrieves document chunks, scoped per-assessment.

Prefers Qdrant (the real vector DB); falls back to an in-memory brute-force
cosine-similarity store - same "InMemoryGraphStore" pattern neo4j_service.py
uses for the graph - so upsert/search stay fully exercisable without a live
Qdrant instance (local dev without Docker, tests).

Per README convention #1, this module must reference app.core.db's
``qdrant_client`` dynamically (``core_db.qdrant_client``), never
``from app.core.db import qdrant_client`` - init_db() sets the real client
*after* this module is first imported.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any, Dict, List, Tuple

from app.core import db as core_db
from app.core.config import settings

logger = logging.getLogger("emios")

try:
    from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
    HAS_QDRANT_MODELS = True
except ImportError:
    HAS_QDRANT_MODELS = False


class _InMemoryVectorStore:
    """Fallback store: {point_id: (vector, payload)}, brute-force cosine search."""

    def __init__(self):
        self._points: Dict[str, Tuple[List[float], Dict[str, Any]]] = {}

    def upsert(self, point_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        self._points[point_id] = (vector, payload)

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, assessment_id: str, query_vector: List[float], top_k: int) -> List[Dict[str, Any]]:
        scored = [
            (self._cosine_similarity(query_vector, vector), payload)
            for vector, payload in self._points.values()
            if payload.get("assessment_id") == assessment_id
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{"score": score, **payload} for score, payload in scored[:top_k]]


# Singleton in-memory fallback, mirrors neo4j_service.py's in_memory_db pattern.
_in_memory_store = _InMemoryVectorStore()


class QdrantVectorStore:
    """Upserts/searches document-chunk embeddings. One collection, filtered by
    ``assessment_id`` in the payload so retrieval stays scoped per-assessment
    even though all assessments' documents share the same collection."""

    def __init__(self, vector_size: int):
        self.vector_size = vector_size
        if core_db.qdrant_client and HAS_QDRANT_MODELS:
            self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = {c.name for c in core_db.qdrant_client.get_collections().collections}
        if settings.QDRANT_COLLECTION_NAME not in existing:
            try:
                core_db.qdrant_client.create_collection(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
            except Exception:
                # A QdrantVectorStore is constructed fresh per upload (see
                # get_vector_store() below) and, since zip members are now
                # processed concurrently, several can race this
                # check-then-create on the very first upload of a fresh
                # deployment. Whoever loses the race just hits "already
                # exists" here - the collection ends up created either way,
                # so this is safe to swallow rather than failing the upload.
                existing_now = {c.name for c in core_db.qdrant_client.get_collections().collections}
                if settings.QDRANT_COLLECTION_NAME not in existing_now:
                    raise

    def upsert_chunks(
        self,
        assessment_id: str,
        upload_id: str,
        chunk_texts: List[str],
        embeddings: List[List[float]],
    ) -> List[str]:
        """Upserts one point per chunk. Returns the generated point ids, in order,
        for the caller to persist alongside each DocumentChunk row."""
        point_ids = [uuid.uuid4().hex for _ in chunk_texts]

        if core_db.qdrant_client and HAS_QDRANT_MODELS:
            try:
                points = [
                    PointStruct(
                        id=point_ids[i],
                        vector=embeddings[i],
                        payload={
                            "assessment_id": assessment_id,
                            "upload_id": upload_id,
                            "chunk_index": i,
                            "text": chunk_texts[i],
                        },
                    )
                    for i in range(len(chunk_texts))
                ]
                core_db.qdrant_client.upsert(collection_name=settings.QDRANT_COLLECTION_NAME, points=points)
                return point_ids
            except Exception as e:
                logger.warning(f"Qdrant upsert failed, falling back to in-memory vector store: {e}")

        for i in range(len(chunk_texts)):
            _in_memory_store.upsert(
                point_ids[i],
                embeddings[i],
                {"assessment_id": assessment_id, "upload_id": upload_id, "chunk_index": i, "text": chunk_texts[i]},
            )
        return point_ids

    def search(self, assessment_id: str, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Returns up to `top_k` chunks {text, score, chunk_index, upload_id},
        highest similarity first, scoped to this assessment's own documents."""
        if core_db.qdrant_client and HAS_QDRANT_MODELS:
            try:
                results = core_db.qdrant_client.query_points(
                    collection_name=settings.QDRANT_COLLECTION_NAME,
                    query=query_vector,
                    query_filter=Filter(
                        must=[FieldCondition(key="assessment_id", match=MatchValue(value=assessment_id))]
                    ),
                    limit=top_k,
                ).points
                return [{"score": r.score, **r.payload} for r in results]
            except Exception as e:
                logger.warning(f"Qdrant search failed, falling back to in-memory vector store: {e}")

        return _in_memory_store.search(assessment_id, query_vector, top_k)


def get_vector_store() -> QdrantVectorStore:
    """Constructs a QdrantVectorStore sized to the currently active embedding
    provider's dimensionality (see app/core/embeddings.py)."""
    from app.core.embeddings import get_embedding_provider

    return QdrantVectorStore(vector_size=get_embedding_provider().dimensions)
