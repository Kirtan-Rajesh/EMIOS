"""Extracts cross-system data dependencies from a dump of stored procedures.

Deliberately regex-based rather than a full SQL parse: vendor procedural SQL
(T-SQL BEGIN/END blocks, PL/pgSQL, PL/SQL control flow, DECLARE/IF/WHILE, ...)
is dialect-specific enough that a generic parser frequently only gets partial
coverage, and silently dropping a proc because its control-flow syntax didn't
parse is worse here than a slightly noisier but far more robust text scan for
FROM/JOIN (reads) and INSERT INTO/UPDATE/DELETE FROM/MERGE INTO (writes).

Uses the same schema-qualifier grouping as SchemaExtractor (a table/proc name
like `payments.transactions` groups under schema "payments" -> node id
"payments_db") specifically so a stored-proc dump and a schema dump describing
the same system converge on identical node ids without needing the fuzzy
entity-resolution pass to reconcile them. A stored procedure that reads or
writes a table in a *different* schema than the one it lives in becomes a
cross-system DB edge - that's the real migration-risk signal here (legacy
systems that bury business logic in stored procs are exactly the case where
"what actually depends on what" is invisible without this kind of scan).
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.base import (
    UNQUALIFIED_SCHEMA as _UNQUALIFIED,
    BaseExtractor,
    ExtractionResult,
    safe_node_id as _safe_id,
)

_PROC_START_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?(?:procedure|function)\s+([a-zA-Z0-9_.\[\]\"]+)",
    re.IGNORECASE,
)
_READ_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z0-9_.\[\]\"]+)", re.IGNORECASE)
_WRITE_RE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|merge\s+into)\s+([a-zA-Z0-9_.\[\]\"]+)",
    re.IGNORECASE,
)
_NOT_A_TABLE = {
    "select", "where", "set", "values", "as", "on", "and", "or", "into", "dbo",
    "begin", "declare", "exec", "table", "procedure", "function",
}


def _clean_name(raw: str) -> str:
    return raw.strip().strip('"').strip("[").strip("]")


def _schema_of(qualified_name: str) -> str:
    parts = _clean_name(qualified_name).split(".")
    return parts[0] if len(parts) > 1 else _UNQUALIFIED


class StoredProcExtractor(BaseExtractor):
    name = "StoredProcExtractor"

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        if not filename.lower().endswith((".sql", ".ddl")):
            return False
        return bool(re.search(r"create\s+(?:or\s+replace\s+)?(?:procedure|function)", text_preview, re.IGNORECASE))

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        sql_text = content.decode("utf-8", errors="replace")
        warnings: List[str] = []

        starts = list(_PROC_START_RE.finditer(sql_text))
        if not starts:
            warnings.append("No CREATE PROCEDURE/FUNCTION statements found in this file.")
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        schemas_seen: Set[str] = set()
        cross_schema_refs: Set[Tuple[str, str, str]] = set()  # (owner_schema, dep_schema, access)
        proc_count = 0

        for idx, match in enumerate(starts):
            proc_count += 1
            proc_name = match.group(1)
            owner_schema = _schema_of(proc_name)
            schemas_seen.add(owner_schema)

            body_start = match.end()
            body_end = starts[idx + 1].start() if idx + 1 < len(starts) else len(sql_text)
            body = sql_text[body_start:body_end]

            for pattern, access in ((_READ_RE, "read"), (_WRITE_RE, "write")):
                for ref_match in pattern.finditer(body):
                    ref = _clean_name(ref_match.group(1))
                    base_token = ref.split(".")[-1].lower()
                    if not ref or base_token in _NOT_A_TABLE or ref.startswith(("@", "#")):
                        continue
                    dep_schema = _schema_of(ref)
                    schemas_seen.add(dep_schema)
                    if dep_schema != owner_schema:
                        cross_schema_refs.add((owner_schema, dep_schema, access))

        if len(schemas_seen) <= 1 and _UNQUALIFIED in schemas_seen:
            warnings.append(
                f"Found {proc_count} stored procedure(s), but none of them or the tables they "
                f"touch are schema-qualified, so no cross-system dependency could be inferred. "
                f"Use schema-qualified names (e.g. 'payments.sp_settle_transaction') for "
                f"finer-grained topology."
            )
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        schema_to_node_id: Dict[str, str] = {s: _safe_id(f"{s}_db") for s in schemas_seen}
        nodes = [
            ServiceNode(
                id=node_id,
                name=f"{schema.title()} Database" if schema != _UNQUALIFIED else "Unqualified Database",
                type="Database",
                business_value="Medium",
                migration_complexity="Medium",
                runtime="SQL (Stored Procedures)",
            )
            for schema, node_id in schema_to_node_id.items()
        ]

        edges = [
            DependencyEdge(
                source=schema_to_node_id[owner_schema],
                target=schema_to_node_id[dep_schema],
                type="DB",
                # Cross-schema writes from within a stored proc are typically
                # synchronous and part of the same transaction - treat as High.
                criticality="High" if access == "write" else "Medium",
                is_discovered=True,
            )
            for owner_schema, dep_schema, access in cross_schema_refs
        ]

        warnings.append(
            f"Scanned {proc_count} stored procedure(s) across {len(schemas_seen)} schema(s); "
            f"found {len(cross_schema_refs)} cross-schema data access pattern(s)."
        )

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=nodes,
            edges=edges,
            warnings=warnings,
            # Regex-based, not a real parse - flagged lower than SchemaExtractor's
            # deterministic DDL parse even though no LLM is involved.
            confidence=0.85,
        )
