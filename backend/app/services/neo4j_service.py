import logging
import csv
import os
from typing import List, Dict, Any, Tuple
from app.core import db as core_db
from app.models.schemas import ServiceNode, DependencyEdge

logger = logging.getLogger("emios")

# In-memory database fallback store
class InMemoryGraphStore:
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []

    def clear(self):
        self.nodes.clear()
        self.edges.clear()

    def add_node(self, node: Dict[str, Any]):
        self.nodes[node["id"]] = node

    def add_edge(self, edge: Dict[str, Any]):
        # Prevent duplicates
        for existing in self.edges:
            if existing["source"] == edge["source"] and existing["target"] == edge["target"]:
                return
        self.edges.append(edge)

    def get_all(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return list(self.nodes.values()), list(self.edges)

# Singleton in-memory store
in_memory_db = InMemoryGraphStore()

# Load default e-commerce demo dataset when graph is empty
def get_demo_dataset() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    nodes = []
    edges = []
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    resources_dir = os.path.join(current_dir, "..", "resources")
    
    nodes_csv_path = os.path.join(resources_dir, "demo_nodes.csv")
    edges_csv_path = os.path.join(resources_dir, "demo_edges.csv")
    
    try:
        if os.path.exists(nodes_csv_path):
            with open(nodes_csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    nodes.append({
                        "id": str(row["id"]),
                        "name": str(row["name"]),
                        "type": str(row.get("type") or "Microservice"),
                        "business_value": str(row.get("business_value") or "Medium"),
                        "revenue_impact": float(row.get("revenue_impact") or 0.0),
                        "migration_complexity": str(row.get("migration_complexity") or "Medium"),
                        "base_cost": float(row.get("base_cost") or 10000.0),
                        "base_duration": int(row.get("base_duration") or 14),
                        "status": "Legacy",
                        "failure_probability": 0.0,
                        "runtime": str(row.get("runtime") or "Unknown"),
                        "annual_cost": float(row.get("annual_cost") or 0.0)
                    })
                    
        if os.path.exists(edges_csv_path):
            with open(edges_csv_path, mode='r', encoding='utf-8') as f:
                reader_edges = csv.DictReader(f)
                for row in reader_edges:
                    edges.append({
                        "source": str(row["source"]),
                        "target": str(row["target"]),
                        "type": str(row.get("type") or "Sync"),
                        "criticality": str(row.get("criticality") or "Medium"),
                        "is_discovered": str(row.get("is_discovered") or "").lower() == 'true'
                    })
    except Exception as ex:
        logger.error(f"Error loading demo dataset from CSV resources: {ex}")
        
    return nodes, edges

def reset_and_populate_graph(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]):
    # Fallback/In-memory reset
    in_memory_db.clear()
    for n in nodes:
        in_memory_db.add_node(n)
    for e in edges:
        in_memory_db.add_edge(e)
        
    if not core_db.neo4j_driver:
        logger.info("Reset graph in in-memory storage.")
        return

    # Neo4j update
    try:
        with core_db.neo4j_driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            
            # Create nodes
            for node in nodes:
                session.run("""
                    CREATE (s:Service {
                        id: $id,
                        name: $name,
                        type: $type,
                        business_value: $business_value,
                        revenue_impact: $revenue_impact,
                        migration_complexity: $migration_complexity,
                        base_cost: $base_cost,
                        base_duration: $base_duration,
                        status: $status,
                        failure_probability: $failure_probability,
                        runtime: $runtime,
                        annual_cost: $annual_cost
                    })
                """, **node)
            
            # Create relationships
            for edge in edges:
                session.run("""
                    MATCH (a:Service {id: $source})
                    MATCH (b:Service {id: $target})
                    CREATE (a)-[r:DEPENDS_ON {
                        type: $type,
                        criticality: $criticality,
                        is_discovered: $is_discovered
                    }]->(b)
                """, **edge)
        logger.info("Successfully populated Neo4j database graph.")
    except Exception as ex:
        logger.error(f"Failed to populate Neo4j: {ex}. Reverted back to memory fallback.")

def get_graph() -> Tuple[List[ServiceNode], List[DependencyEdge]]:
    # Attempt to load from Neo4j
    if core_db.neo4j_driver:
        try:
            nodes = []
            edges = []
            with core_db.neo4j_driver.session() as session:
                result_nodes = session.run("MATCH (s:Service) RETURN s")
                for record in result_nodes:
                    node_props = dict(record["s"])
                    nodes.append(ServiceNode(**node_props))
                
                result_edges = session.run("MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) RETURN a.id, b.id, r")
                for record in result_edges:
                    rel = record["r"]
                    edges.append(DependencyEdge(
                        source=record["a.id"],
                        target=record["b.id"],
                        type=rel.get("type", "Sync"),
                        criticality=rel.get("criticality", "Medium"),
                        is_discovered=rel.get("is_discovered", False)
                    ))
            
            # If empty, populate demo
            if not nodes:
                demo_nodes, demo_edges = get_demo_dataset()
                reset_and_populate_graph(demo_nodes, demo_edges)
                return get_graph()

            return nodes, edges
        except Exception as ex:
            logger.error(f"Failed to fetch Neo4j graph: {ex}. Falling back to In-Memory.")

    # In-memory database loading
    mem_nodes, mem_edges = in_memory_db.get_all()
    if not mem_nodes:
        # Populate demo dataset
        demo_nodes, demo_edges = get_demo_dataset()
        reset_and_populate_graph(demo_nodes, demo_edges)
        mem_nodes, mem_edges = in_memory_db.get_all()

    nodes = [ServiceNode(**n) for n in mem_nodes]
    edges = [DependencyEdge(**e) for e in mem_edges]
    return nodes, edges

def add_discovered_edges(edges: List[Dict[str, Any]]):
    for edge in edges:
        in_memory_db.add_edge(edge)
        
    if core_db.neo4j_driver:
        try:
            with core_db.neo4j_driver.session() as session:
                for edge in edges:
                    session.run("""
                        MATCH (a:Service {id: $source})
                        MATCH (b:Service {id: $target})
                        MERGE (a)-[r:DEPENDS_ON {type: $type, criticality: $criticality}]->(b)
                        ON CREATE SET r.is_discovered = true
                    """, **edge)
            logger.info("Successfully merged discovered edges in Neo4j.")
        except Exception as ex:
            logger.error(f"Failed to write discovered edges to Neo4j: {ex}.")
