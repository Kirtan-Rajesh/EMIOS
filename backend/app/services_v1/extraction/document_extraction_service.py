"""Dispatches a batch of uploaded documents to the right extractor(s) and
merges their results into one graph contribution.

Dispatch is content-sniff based, not purely extension based, and multiple
structured extractors may legitimately claim the same file - most notably a
single .sql dump that contains both CREATE TABLE and CREATE PROCEDURE
statements is run through both SchemaExtractor and StoredProcExtractor, not
"first match wins". Only when *no* structured extractor claims a document does
it fall through to the LLM-based BRD/HLD extractor - the expensive, lower-
confidence catch-all, used deliberately last.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.api_spec_extractor import ApiSpecExtractor
from app.services_v1.extraction.base import BaseExtractor, ExtractionResult
from app.services_v1.extraction.entity_resolution import merge_extraction_results
from app.services_v1.extraction.etl_mapping_extractor import EtlMappingExtractor
from app.services_v1.extraction.llm_prompt_extractor import LlmPromptExtractor
from app.services_v1.extraction.metadata_extractor import MetadataExtractor
from app.services_v1.extraction.schema_extractor import SchemaExtractor
from app.services_v1.extraction.stored_proc_extractor import StoredProcExtractor

_PREVIEW_CHARS = 4000


class DocumentExtractionService:
    def __init__(self):
        self._structured_extractors: List[BaseExtractor] = [
            SchemaExtractor(),
            StoredProcExtractor(),
            ApiSpecExtractor(),
            EtlMappingExtractor(),
            MetadataExtractor(),
        ]
        self._fallback_extractor = LlmPromptExtractor()

    def extract_document(self, filename: str, content: bytes) -> List[ExtractionResult]:
        text_preview = content[:_PREVIEW_CHARS].decode("utf-8", errors="ignore")
        matched = [e for e in self._structured_extractors if e.can_handle(filename, text_preview, content)]
        if not matched:
            return [self._fallback_extractor.extract(filename, content, text_preview)]
        return [extractor.extract(filename, content, text_preview) for extractor in matched]

    def extract_documents(
        self, documents: List[Tuple[str, bytes]]
    ) -> Tuple[List[ServiceNode], List[DependencyEdge], List[str], Dict[str, Any]]:
        if not documents:
            return [], [], ["No documents were provided for discovery."], {"per_document": [], "overall_confidence": 0.0}

        all_results: List[ExtractionResult] = []
        for filename, content in documents:
            all_results.extend(self.extract_document(filename, content))

        nodes, edges, warnings = merge_extraction_results(all_results)

        per_document = [
            {
                "filename": r.source_filename,
                "extractor": r.extractor,
                "nodes_found": len(r.nodes),
                "edges_found": len(r.edges),
                "confidence": r.confidence,
            }
            for r in all_results
        ]
        overall_confidence = round(sum(r.confidence for r in all_results) / len(all_results), 2)

        return nodes, edges, warnings, {"per_document": per_document, "overall_confidence": overall_confidence}
