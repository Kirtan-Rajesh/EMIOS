"""Pydantic v2 response schemas for the Assessment Graph Persistence module.

The request body deliberately reuses ``app.models.schemas.GraphData`` (the same
shape the existing legacy ingestion pipeline accepts) rather than inventing a new
schema - see app/api/v1/graph.py.
"""

from typing import List

from pydantic import BaseModel

from app.models.schemas import DependencyEdge, ServiceNode


class GraphPersistResponse(BaseModel):
    assessment_id: str
    node_count: int
    edge_count: int
    graph_status: str


class GraphResponse(BaseModel):
    assessment_id: str
    nodes: List[ServiceNode]
    edges: List[DependencyEdge]
