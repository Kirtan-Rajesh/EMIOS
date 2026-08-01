"""Extracts systems and dependencies from free-text project documentation
(BRD/HLD) via an LLM - there is no deterministic fallback possible for prose,
unlike every other agent in this codebase (which computes real values in
Python and only uses the LLM to narrate them). If no LLM provider is
configured, this extractor honestly returns zero nodes/edges with a warning,
rather than fabricating anything.

Confidence is fixed lower than the deterministic extractors (0.55) to signal
to callers/UI that LLM-derived nodes from prose carry real hallucination risk
and should get human review before they're trusted to drive a migration plan -
see the architecture discussion this implements.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.agents import prompts
from app.core.llm_provider import invoke_with_fallback
from app.models.schemas import DependencyEdge, ServiceNode
from app.services.document_processing_service import DocumentProcessingService
from app.services_v1.extraction.base import BaseExtractor, ExtractionResult, safe_node_id
from app.services_v1.extraction.entity_resolution import normalize_key

_MAX_DOCUMENT_CHARS = 12000
_UNCONFIGURED_FALLBACK = json.dumps(
    {
        "systems": [],
        "dependencies": [],
        "agent_log": (
            "LLM extraction unavailable - no LLM provider is configured. No structured data "
            "was extracted from this document; add relevant systems manually or configure an "
            "LLM provider (see app/core/llm_provider.py) and re-run discovery."
        ),
    }
)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

# Enterprise documents routinely cite each other by filename ("see the 'Cloud
# Readiness' field in Application_Inventory_Master.xlsx") - the prompt tells the
# LLM not to extract those as systems, but that's not something to trust alone
# (observed directly: a small/fast model still did it despite the instruction).
# This is the deterministic backstop: a bare filename, with or without a folder
# path in front of it, is never a real system name.
_DOCUMENT_FILENAME_RE = re.compile(
    r"(^|[\\/])[^\\/]+\.(xlsx|xls|docx|doc|csv|pdf|pptx|ppt|txt|json|md)$", re.IGNORECASE
)


def _strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _looks_like_document_filename(name: str) -> bool:
    return bool(_DOCUMENT_FILENAME_RE.search(name.strip()))


def _coerce_positive_float(value: Any) -> float:
    """The prompt asks for a non-zero cost/revenue estimate per system, but a
    small/fast model can still omit the field, return a string, or (having no
    real grounding) guess something negative - fall back to the ServiceNode
    default (0.0) rather than letting a malformed value raise or propagate."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


class LlmPromptExtractor(BaseExtractor):
    name = "LlmPromptExtractor"
    confidence = 0.55

    def __init__(self):
        # chunk_repo is only used by DocumentProcessingService.process() (the
        # RAG chunk/embed/store pipeline), never by extract_text() - safe to
        # pass None here since we only want text extraction.
        self._doc_processor = DocumentProcessingService(chunk_repo=None)

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        # Catch-all: anything none of the deterministic extractors claimed
        # (see DocumentExtractionService's dispatch order) is treated as
        # free-text project documentation.
        return True

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        content_type_hint = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }.get(_ext(filename), "")

        try:
            text = self._doc_processor.extract_text(content, content_type_hint, filename)
        except Exception as ex:
            return ExtractionResult(
                source_filename=filename,
                extractor=self.name,
                warnings=[f"Could not extract text from '{filename}': {ex}"],
                confidence=0.0,
            )

        text = text.strip()
        if not text:
            return ExtractionResult(
                source_filename=filename,
                extractor=self.name,
                warnings=["No extractable text found in this document."],
                confidence=0.0,
            )

        warnings: List[str] = []
        truncated = text[:_MAX_DOCUMENT_CHARS]
        if len(text) > _MAX_DOCUMENT_CHARS:
            warnings.append(
                f"Document is {len(text)} characters; only the first {_MAX_DOCUMENT_CHARS} were "
                f"sent to the LLM for extraction. Split large documents for full coverage."
            )

        sys_prompt = prompts.DISCOVERY_EXTRACTION_SYSTEM_PROMPT
        usr_prompt = prompts.DISCOVERY_EXTRACTION_USER_PROMPT.format(filename=filename, document_text=truncated)

        raw_output = invoke_with_fallback(
            sys_prompt, usr_prompt, "Document Extraction Agent (BRD/HLD)", _UNCONFIGURED_FALLBACK
        )

        try:
            parsed: Dict[str, Any] = json.loads(_strip_code_fence(raw_output))
        except (json.JSONDecodeError, TypeError):
            warnings.append(
                f"LLM response was not valid JSON; no data extracted from this document. "
                f"Response preview: {raw_output[:200]!r}"
            )
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings, confidence=0.0)

        systems = parsed.get("systems") or []
        dependencies = parsed.get("dependencies") or []
        agent_log = parsed.get("agent_log", "")
        if agent_log:
            warnings.append(f"Extraction summary: {agent_log}")

        name_to_id: Dict[str, str] = {}
        # Same-document dependencies routinely name a system slightly differently
        # than the systems list did in the same LLM response ("Payment Service" vs
        # "Payment Svc", "the Payment Service", ...) - a small/fast model is not
        # internally consistent about this. Keyed by normalize_key() (the same
        # abbreviation/punctuation/case-insensitive identity key entity_resolution
        # uses across documents) so a dependency naming a system this document
        # already extracted still resolves to that node's real id below, instead
        # of silently minting an unmatched id that entity_resolution then drops
        # the edge over.
        normalized_name_to_id: Dict[str, str] = {}
        nodes: List[ServiceNode] = []
        for system in systems:
            name = (system or {}).get("name")
            if not name or not isinstance(name, str):
                continue
            if _looks_like_document_filename(name):
                warnings.append(
                    f"Skipped extracted system '{name}': looks like a citation to another source "
                    f"document (a filename), not an actual system."
                )
                continue
            node_id = safe_node_id(name)
            if node_id in name_to_id.values():
                continue
            name_to_id[name] = node_id
            normalized_name_to_id[normalize_key(name)] = node_id
            criticality = (system.get("criticality") or "Medium").title()
            if criticality not in ("High", "Medium", "Low"):
                criticality = "Medium"
            nodes.append(
                ServiceNode(
                    id=node_id,
                    name=name,
                    type="Microservice",
                    business_value=criticality,
                    migration_complexity="Medium",
                    runtime="Unknown",
                    annual_cost=_coerce_positive_float(system.get("annual_cost")),
                    revenue_impact=_coerce_positive_float(system.get("revenue_impact")),
                )
            )

        edges: List[DependencyEdge] = []
        seen_pairs = set()
        for dep in dependencies:
            source_name = (dep or {}).get("source")
            target_name = (dep or {}).get("target")
            if not source_name or not target_name:
                continue
            source_id = (
                name_to_id.get(source_name)
                or normalized_name_to_id.get(normalize_key(source_name))
                or safe_node_id(source_name)
            )
            target_id = (
                name_to_id.get(target_name)
                or normalized_name_to_id.get(normalize_key(target_name))
                or safe_node_id(target_name)
            )
            if source_id == target_id or (source_id, target_id) in seen_pairs:
                continue
            seen_pairs.add((source_id, target_id))
            edges.append(DependencyEdge(source=source_id, target=target_id, type="Sync", criticality="Medium", is_discovered=True))

        warnings.append(
            f"LLM-extracted {len(nodes)} system(s) and {len(edges)} dependency(ies) from "
            f"'{filename}' - review before trusting this to drive a migration plan."
        )

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=nodes,
            edges=edges,
            warnings=warnings,
            confidence=self.confidence,
        )


def _ext(filename: str) -> str:
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""
