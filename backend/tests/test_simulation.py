import pytest
from app.models.schemas import ServiceNode, DependencyEdge
from app.services.simulation_engine import run_cascading_failure, run_monte_carlo

@pytest.fixture
def sample_graph():
    """Provides a basic 3-node graph representing database, service, and monolith dependencies."""
    # Arrange
    nodes = [
        ServiceNode(id="db", name="User DB", type="Database", business_value="High", annual_cost=50000, revenue_impact=10000),
        ServiceNode(id="service", name="User Service", type="Microservice", business_value="High", annual_cost=15000, revenue_impact=2000),
        ServiceNode(id="monolith", name="Core Monolith", type="Monolith", business_value="Low", annual_cost=80000, revenue_impact=5000)
    ]
    edges = [
        DependencyEdge(source="service", target="db", type="DB", criticality="High"),
        DependencyEdge(source="monolith", target="service", type="Sync", criticality="High")
    ]
    return nodes, edges

def test_cascading_failure_propagation(sample_graph):
    # Arrange
    nodes, edges = sample_graph
    
    # Act
    impacted_nodes, critical_paths, revenue_at_risk = run_cascading_failure(
        nodes=nodes,
        edges=edges,
        target_id="db",
        already_migrated=[]
    )
    
    # Assert
    # Failing 'db' should propagate up to 'service' and 'monolith'
    impacted_ids = [n.id for n in impacted_nodes]
    assert "db" in impacted_ids
    assert "service" in impacted_ids
    assert "monolith" in impacted_ids
    assert len(critical_paths) >= 2
    assert revenue_at_risk > 0.0

def test_monte_carlo_timeline_simulation(sample_graph):
    # Arrange
    nodes, edges = sample_graph
    impacted_nodes, _, _ = run_cascading_failure(nodes=nodes, edges=edges, target_id="db", already_migrated=[])
    
    # Act
    result = run_monte_carlo(nodes=nodes, impacted_nodes=impacted_nodes, num_simulations=500)
    
    # Assert
    assert result.expected_duration > 0
    assert result.expected_cost > 0
    assert len(result.distribution) == 20
    assert result.confidence_90_duration[0] <= result.confidence_90_duration[1]
    assert result.confidence_90_cost[0] <= result.confidence_90_cost[1]
