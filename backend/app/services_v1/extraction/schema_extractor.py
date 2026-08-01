"""Extracts nodes/edges from a SQL DDL dump (CREATE TABLE + FOREIGN KEY/REFERENCES).

Granularity note: individual tables are NOT modeled as separate graph nodes -
that would explode the graph far past the system-level granularity every other
part of this platform (ServiceNode, the 12-agent pipeline, simulation) assumes.
Instead, tables are grouped by their schema/database qualifier (e.g.
`payments.transactions` -> schema "payments"), and each distinct schema becomes
one Database node. A foreign key whose referenced table lives in a *different*
schema becomes a cross-system DB dependency edge - that is the genuinely
interesting migration-planning signal a schema dump can offer; FKs within the
same schema are just internal table structure and are not surfaced as edges.

If none of the tables are schema-qualified, there is no basis to split the
file into multiple systems, so the whole file becomes a single Database node
(named from the filename) - flagged with a warning so a human knows finer
granularity would require schema-qualified names.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import sqlglot
from sqlglot import exp

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.base import (
    UNQUALIFIED_SCHEMA as _UNQUALIFIED,
    BaseExtractor,
    ExtractionResult,
    safe_node_id as _safe_id,
)


class SchemaExtractor(BaseExtractor):
    name = "SchemaExtractor"

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        if not filename.lower().endswith((".sql", ".ddl")):
            return False
        return bool(re.search(r"create\s+table", text_preview, re.IGNORECASE))

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        warnings: List[str] = []
        sql_text = content.decode("utf-8", errors="replace")

        try:
            statements = sqlglot.parse(sql_text, error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception as ex:
            return ExtractionResult(
                source_filename=filename,
                extractor=self.name,
                warnings=[f"Could not parse SQL: {ex}"],
                confidence=0.0,
            )

        schema_tables: Dict[str, List[str]] = {}
        cross_schema_refs: Set[Tuple[str, str]] = set()

        for stmt in statements:
            if stmt is None or not isinstance(stmt, exp.Create):
                continue
            if str(stmt.args.get("kind", "")).upper() != "TABLE":
                continue

            table_exp = stmt.find(exp.Table)
            if table_exp is None:
                continue

            schema_part = table_exp.db or _UNQUALIFIED
            schema_tables.setdefault(schema_part, []).append(table_exp.name)

            for ref in stmt.find_all(exp.Reference):
                ref_table = ref.find(exp.Table)
                if ref_table is None:
                    continue
                ref_schema = ref_table.db or schema_part
                if ref_schema != schema_part:
                    cross_schema_refs.add((schema_part, ref_schema))

        if not schema_tables:
            warnings.append("No CREATE TABLE statements found in this file.")
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        schema_to_node_id: Dict[str, str] = {}
        nodes: List[ServiceNode] = []
        file_stem = Path(filename).stem

        if list(schema_tables.keys()) == [_UNQUALIFIED]:
            warnings.append(
                f"No schema-qualified table names found - all {len(schema_tables[_UNQUALIFIED])} "
                f"table(s) were grouped into a single Database node for this file. Use "
                f"schema-qualified names (e.g. 'payments.transactions') for finer-grained topology."
            )

        for schema_name, tables in schema_tables.items():
            if schema_name == _UNQUALIFIED:
                node_id = _safe_id(file_stem)
                display_name = f"{file_stem} Database"
            else:
                node_id = _safe_id(f"{schema_name}_db")
                display_name = f"{schema_name.title()} Database"

            table_count = len(tables)
            complexity = "High" if table_count > 20 else ("Medium" if table_count > 5 else "Low")

            schema_to_node_id[schema_name] = node_id
            nodes.append(
                ServiceNode(
                    id=node_id,
                    name=display_name,
                    type="Database",
                    business_value="Medium",
                    migration_complexity=complexity,
                    runtime="SQL",
                )
            )
            warnings.append(f"Schema '{schema_name}' -> node '{node_id}': {table_count} table(s) found.")

        edges: List[DependencyEdge] = []
        for source_schema, target_schema in cross_schema_refs:
            edges.append(
                DependencyEdge(
                    source=schema_to_node_id[source_schema],
                    target=schema_to_node_id[target_schema],
                    type="DB",
                    criticality="Medium",
                    is_discovered=True,
                )
            )

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=nodes,
            edges=edges,
            warnings=warnings,
            confidence=1.0,
        )
