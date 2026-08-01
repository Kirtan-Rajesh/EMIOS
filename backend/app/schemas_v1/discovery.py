"""Pydantic v2 response schema for the Document Discovery module."""

from typing import Any, Dict, List

from pydantic import BaseModel


class DiscoveryResponse(BaseModel):
    assessment_id: str
    status: str  # "graph_updated" or "no_data_extracted"
    node_count: int
    edge_count: int
    graph_status: str = ""
    warnings: List[str] = []
    extraction_report: Dict[str, Any] = {}
