"""Extracts dependency edges from an ETL mapping spreadsheet (source system/table
-> target system/table) - CSV or XLSX.

Referenced systems that aren't already known nodes get a minimal placeholder
ServiceNode (defaults across the board) so the edge has somewhere to attach -
DocumentExtractionService's merge pass will fold these into a richer node from
another document (e.g. the DB Schema or Metadata extractor) if one describes
the same system, via entity_resolution's name normalization.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.base import (
    BaseExtractor,
    ExtractionResult,
    read_tabular_rows,
    safe_node_id,
    sniff_header_line,
)

_SOURCE_KEYS = [
    "source system", "source_system", "from system", "source", "src system", "src_system",
    # "Application" as the calling/owning side of a dependency row (e.g. a
    # Dependency Matrix's "Application | Relationship Type | Target" shape) is
    # at least as common in real inventory exports as "source system".
    "application",
]
_TARGET_KEYS = ["target system", "target_system", "to system", "target", "tgt system", "tgt_system"]
_TYPE_KEYS = ["connection type", "type", "relationship type"]
_CRITICALITY_KEYS = ["importance", "criticality", "app criticality"]


def _resolve(row: Dict[str, str], keys: List[str], default: Optional[str] = None) -> Optional[str]:
    lower_row = {k.strip().lower(): v for k, v in row.items() if k}
    for key in keys:
        if key in lower_row and lower_row[key] and lower_row[key].strip():
            return lower_row[key].strip()
    return default


class EtlMappingExtractor(BaseExtractor):
    name = "EtlMappingExtractor"

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        if not filename.lower().endswith((".csv", ".xlsx")):
            return False
        header_line = sniff_header_line(filename, content)
        has_source = any(k in header_line for k in _SOURCE_KEYS)
        has_target = any(k in header_line for k in _TARGET_KEYS)
        return has_source and has_target

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        warnings: List[str] = []

        rows = read_tabular_rows(filename, content)
        if not rows:
            warnings.append("File has no header row or no data rows.")
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        node_ids: Dict[str, ServiceNode] = {}
        edges: List[DependencyEdge] = []
        seen_pairs = set()

        for row_num, row in enumerate(rows, start=2):
            source_name = _resolve(row, _SOURCE_KEYS)
            target_name = _resolve(row, _TARGET_KEYS)
            if not source_name or not target_name:
                warnings.append(f"Row {row_num} skipped: missing source and/or target system.")
                continue

            source_id = safe_node_id(source_name)
            target_id = safe_node_id(target_name)

            for node_id, display_name in ((source_id, source_name), (target_id, target_name)):
                if node_id not in node_ids:
                    node_ids[node_id] = ServiceNode(id=node_id, name=display_name, type="Microservice")

            if source_id == target_id:
                warnings.append(f"Row {row_num} skipped: self-referential mapping on '{source_name}'.")
                continue

            pair = (source_id, target_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            edges.append(
                DependencyEdge(
                    source=source_id,
                    target=target_id,
                    # ETL flows are batch/async data movement by default, unlike
                    # the request/response "Sync" default used elsewhere.
                    type=_resolve(row, _TYPE_KEYS, "Async"),
                    criticality=_resolve(row, _CRITICALITY_KEYS, "Medium"),
                    is_discovered=True,
                )
            )

        warnings.append(f"Parsed {len(edges)} ETL mapping(s) covering {len(node_ids)} system(s).")

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=list(node_ids.values()),
            edges=edges,
            warnings=warnings,
            confidence=1.0,
        )
