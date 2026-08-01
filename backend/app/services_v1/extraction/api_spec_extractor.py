"""Extracts a service node from an OpenAPI/Swagger spec (JSON or YAML).

An API spec describes one service's own interface, not its downstream
dependencies - OpenAPI has no standard field for "what does this service call."
So this extractor is honest about what it can actually contribute: one node
per spec (named from `info.title`), with `migration_complexity` inferred from
the number of paths/operations (a reasonable proxy for integration surface
area), and zero edges unless the spec happens to carry the non-standard
`x-dependencies` / `x-upstream-services` vendor extension some API design
tools emit - which, if present, is used to produce edges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.models.schemas import DependencyEdge, ServiceNode
from app.services_v1.extraction.base import BaseExtractor, ExtractionResult, safe_node_id


class ApiSpecExtractor(BaseExtractor):
    name = "ApiSpecExtractor"

    def can_handle(self, filename: str, text_preview: str, content: bytes = b"") -> bool:
        lower = filename.lower()
        if not lower.endswith((".json", ".yaml", ".yml")):
            return False
        preview_lower = text_preview.lower()
        return '"openapi"' in preview_lower or "openapi:" in preview_lower or '"swagger"' in preview_lower or "swagger:" in preview_lower

    def extract(self, filename: str, content: bytes, text_preview: str) -> ExtractionResult:
        text = content.decode("utf-8", errors="replace")
        warnings: List[str] = []

        spec: Dict[str, Any] = {}
        try:
            if filename.lower().endswith(".json"):
                spec = json.loads(text)
            else:
                spec = yaml.safe_load(text) or {}
        except (json.JSONDecodeError, yaml.YAMLError) as ex:
            return ExtractionResult(
                source_filename=filename,
                extractor=self.name,
                warnings=[f"Could not parse API spec: {ex}"],
                confidence=0.0,
            )

        if not isinstance(spec, dict) or ("openapi" not in spec and "swagger" not in spec):
            warnings.append("File did not contain a recognizable 'openapi' or 'swagger' root key.")
            return ExtractionResult(source_filename=filename, extractor=self.name, warnings=warnings)

        info = spec.get("info") or {}
        title = info.get("title") or Path(filename).stem
        version = info.get("version", "")
        paths = spec.get("paths") or {}
        operation_count = sum(
            1
            for path_item in paths.values()
            if isinstance(path_item, dict)
            for method in path_item
            if method.lower() in ("get", "post", "put", "patch", "delete")
        )
        complexity = "High" if operation_count > 30 else ("Medium" if operation_count > 10 else "Low")

        node_id = safe_node_id(title)
        node = ServiceNode(
            id=node_id,
            name=title,
            type="Microservice",
            business_value="Medium",
            migration_complexity=complexity,
            runtime=f"REST API (OpenAPI {spec.get('openapi', spec.get('swagger', ''))})".strip(),
        )
        warnings.append(f"'{title}'{f' v{version}' if version else ''}: {operation_count} operation(s) across {len(paths)} path(s).")

        edges: List[DependencyEdge] = []
        upstream = spec.get("x-dependencies") or spec.get("x-upstream-services") or []
        if isinstance(upstream, list):
            for dep in upstream:
                dep_name = dep.get("service") if isinstance(dep, dict) else dep
                if not dep_name:
                    continue
                edges.append(
                    DependencyEdge(
                        source=node_id,
                        target=safe_node_id(str(dep_name)),
                        type="Sync",
                        criticality="Medium",
                        is_discovered=True,
                    )
                )
            if edges:
                warnings.append(f"Found {len(edges)} declared dependency(ies) via 'x-dependencies'/'x-upstream-services'.")

        return ExtractionResult(
            source_filename=filename,
            extractor=self.name,
            nodes=[node],
            edges=edges,
            warnings=warnings,
            confidence=1.0,
        )
