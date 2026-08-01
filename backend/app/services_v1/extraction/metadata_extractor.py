"""Extracts nodes from a system/application metadata catalog - CSV or XLSX,
the one document type of the original seven that's already close to this
platform's native shape. Recognizes both the canonical snake_case headers
(id,name,type,business_value,...) and the human-friendly ones the
GET /templates/download endpoint hands out (System ID, System Name, Category,
Priority, ...), same alias convention as the legacy CSV ingestion in
app/api/endpoints.py, kept intentionally small here (not the full alias list)
since this is a narrower, purpose-built path.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.models.schemas import ServiceNode
from app.services_v1.extraction.base import (
    BaseExtractor,
    ExtractionResult,
    read_tabular_rows,
    safe_node_id,
    sniff_header_line,
)

_ID_KEYS = ["id", "system id", "app id", "system_id", "application id", "application_id"]
_NAME_KEYS = ["name", "system name", "app name", "system_name", "application name", "application_name"]
_TYPE_KEYS = ["type", "category"]
# "criticality" maps here (not just business_value/priority) because
# _PRIORITY_NORMALIZE below already has a "critical" -> "High" entry ready for
# exactly this real-world column name (Critical/High/Medium/Low is a standard
# enterprise app-inventory field) - it just wasn't wired into the lookup keys.
_PRIORITY_KEYS = ["business_value", "priority", "business value", "criticality"]
_COMPLEXITY_KEYS = ["migration_complexity", "complexity", "migration complexity"]
_RUNTIME_KEYS = ["runtime", "tech stack", "language", "technology stack"]
_ANNUAL_COST_KEYS = ["annual_cost", "annual hosting cost ($)", "annual cost", "hosting cost"]

_PRIORITY_NORMALIZE = {"critical": "High", "high": "High", "p1": "High", "p2": "High", "medium": "Medium", "p3": "Medium"}


def _resolve(row: Dict[str, str], keys: List[str], default: Optional[str] = None) -> Optional[str]:
    lower_row = {k.strip().lower(): v for k, v in row.items() if k}
    for key in keys:
        if key in lower_row and lower_row[key] and lower_row[key].strip():
            return lower_row[key].strip()
    return default


class MetadataExtractor(BaseExtractor):
    name = "MetadataExtractor"

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        if not filename.lower().endswith((".csv", ".xlsx")):
            return False
        header_line = sniff_header_line(filename, content)
        has_id = any(k in header_line for k in _ID_KEYS)
        has_name = any(k in header_line for k in _NAME_KEYS)
        return has_id and has_name

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        warnings: List[str] = []

        rows = read_tabular_rows(filename, content)
        if not rows:
            warnings.append("File has no header row or no data rows.")
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        nodes: List[ServiceNode] = []
        for row_num, row in enumerate(rows, start=2):
            raw_id = _resolve(row, _ID_KEYS)
            name = _resolve(row, _NAME_KEYS)
            if not raw_id or not name:
                warnings.append(f"Row {row_num} skipped: missing id and/or name.")
                continue

            raw_priority = (_resolve(row, _PRIORITY_KEYS, "Medium") or "Medium").lower()
            business_value = _PRIORITY_NORMALIZE.get(raw_priority, "Low" if raw_priority not in ("high", "medium") else raw_priority.title())

            annual_cost_raw = _resolve(row, _ANNUAL_COST_KEYS, "0")
            try:
                annual_cost = float(annual_cost_raw)
            except (TypeError, ValueError):
                annual_cost = 0.0
                warnings.append(f"Row {row_num} ('{name}'): invalid annual cost '{annual_cost_raw}', defaulted to $0.0.")

            nodes.append(
                ServiceNode(
                    id=safe_node_id(raw_id),
                    name=name,
                    type=_resolve(row, _TYPE_KEYS, "Microservice"),
                    business_value=business_value,
                    migration_complexity=_resolve(row, _COMPLEXITY_KEYS, "Medium"),
                    runtime=_resolve(row, _RUNTIME_KEYS, "Unknown"),
                    annual_cost=annual_cost,
                )
            )

        warnings.append(f"Parsed {len(nodes)} system(s) from metadata catalog.")

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=nodes,
            edges=[],
            warnings=warnings,
            confidence=1.0,
        )
