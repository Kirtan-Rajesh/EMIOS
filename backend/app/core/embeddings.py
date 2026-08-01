"""Text embedding provider for RAG (see app/services/vector_search_service.py).

Same Bedrock-preferred, degrade-gracefully priority chain as
app/core/llm_provider.py, with one important difference: embeddings can't be
tried-per-call like the LLM chain, because every document in a single Qdrant
collection must share one embedding space/dimensionality. get_embedding_provider()
therefore picks and memoizes ONE provider the first time it's called, rather than
iterating a list per request.

If no real provider is configured (no AWS/OpenAI credentials), a small
deterministic local embedder is used instead - not semantically meaningful, but
it keeps the full chunk -> embed -> store -> search pipeline exercisable in
tests/local dev without any cloud credentials, matching the same tests-never-
require-live-infra convention the rest of the persistence layer follows.
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
from typing import List, Optional

from app.core.config import get_boto3_client, settings
from app.core.llm_provider import is_configured

logger = logging.getLogger("emios")


class EmbeddingProvider(abc.ABC):
    name: str = "unknown"
    dimensions: int = 0

    @abc.abstractmethod
    def embed(self, text: str) -> List[float]:
        raise NotImplementedError


class BedrockEmbeddingProvider(EmbeddingProvider):
    """Amazon Titan Text Embeddings via boto3's bedrock-runtime, direct (no
    langchain-aws - see app/core/llm_provider.py's BedrockProvider docstring for
    why). Constructor verifies Bedrock access the same cheap way BedrockProvider
    does, without invoking a model."""

    name = "bedrock"
    dimensions = settings.BEDROCK_EMBEDDING_DIMENSIONS

    def __init__(self):
        get_boto3_client("bedrock").list_foundation_models()
        self._runtime = get_boto3_client("bedrock-runtime")

    def embed(self, text: str) -> List[float]:
        body = json.dumps({"inputText": text, "dimensions": self.dimensions})
        response = self._runtime.invoke_model(modelId=settings.BEDROCK_EMBEDDING_MODEL_ID, body=body)
        payload = json.loads(response["body"].read())
        return payload["embedding"]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"
    dimensions = 1536

    def __init__(self):
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        # Cheap request that validates the key without embedding real content.
        self._client.models.list()

    def embed(self, text: str) -> List[float]:
        response = self._client.embeddings.create(model=settings.OPENAI_EMBEDDING_MODEL, input=text)
        return response.data[0].embedding


class DeterministicLocalEmbeddingProvider(EmbeddingProvider):
    """Hash-based pseudo-embedding - NOT semantically meaningful (similarity
    scores won't reflect real relatedness), but deterministic and dependency-free
    so the RAG plumbing (chunk -> embed -> Qdrant upsert -> search) is fully
    testable without any cloud credentials. Fills the same role as the LLM
    provider chain's canned deterministic fallback text."""

    name = "deterministic_local"
    dimensions = 384

    def embed(self, text: str) -> List[float]:
        seed = text.encode("utf-8")
        vector = []
        for i in range(self.dimensions):
            digest = hashlib.sha256(seed + i.to_bytes(4, "little")).digest()
            unit_interval = int.from_bytes(digest[:4], "little") / 0xFFFFFFFF  # [0, 1]
            vector.append(unit_interval * 2 - 1)  # [-1, 1]
        return vector


_embedding_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """Returns the single active embedding provider, memoized after the first
    call (see module docstring for why this can't be a per-call fallback chain
    like get_llm_providers())."""
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider

    try:
        _embedding_provider = BedrockEmbeddingProvider()
        logger.info("Using Bedrock (Titan) for document embeddings.")
        return _embedding_provider
    except Exception as e:
        # WARNING, not debug - this is a real degradation (documents will fall
        # through to the non-semantic local embedder below) and was previously
        # logged at a level invisible under the app's default INFO threshold,
        # meaning "why did upload/RAG search silently stop being meaningful"
        # left no trace at all.
        logger.warning(f"Bedrock embeddings unavailable ({type(e).__name__}: {e}) - trying next provider.")

    if is_configured(settings.OPENAI_API_KEY):
        try:
            _embedding_provider = OpenAIEmbeddingProvider()
            logger.info("Using OpenAI for document embeddings.")
            return _embedding_provider
        except Exception as e:
            logger.warning(f"OpenAI embeddings unavailable ({type(e).__name__}: {e}) - trying next provider.")

    logger.warning(
        "No real embedding provider configured (Bedrock/OpenAI) - falling back to a "
        "deterministic local pseudo-embedder. RAG retrieval will not be semantically "
        "meaningful until a real provider is configured."
    )
    _embedding_provider = DeterministicLocalEmbeddingProvider()
    return _embedding_provider


def reset_embedding_provider_cache() -> None:
    """Test-only hook: clears the memoized provider so tests can run without
    whatever real credentials happen to be configured in the process env."""
    global _embedding_provider
    _embedding_provider = None
