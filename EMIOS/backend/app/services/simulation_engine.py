import random
import networkx as nx
from typing import List, Dict, Any, Tuple
from app.models.schemas import ServiceNode, DependencyEdge, MonteCarloResult
from app.core import constants
from app.core.config import settings

def run_cascading_failure(
    nodes: List[ServiceNode],
    edges: List[DependencyEdge],
    target_id: str,
    already_migrated: List[str]
) -> Tuple[List[ServiceNode], List[List[str]], float]:
    """
    Computes cascading risk propagation when migrating a target service.
    Propagates failure probability upstream to services that depend on this service.
    """
    # Build dependency graph
    # Node dependencies are structured as: Source DEPENDS_ON Target.
    # Therefore, if Target is affected, its Source (client) is affected.
    # We construct a directed graph where edges point from TARGET (dependency) to SOURCE (client)
    # to naturally traverse downstream impact.
    G = nx.DiGraph()
    for node in nodes:
        G.add_node(node.id, data=node)
    
    # Store edges in memory for quick lookups
    edge_map = {}
    for edge in edges:
        G.add_edge(edge.target, edge.source, weight=edge.criticality)
        edge_map[(edge.target, edge.source)] = edge

    impacted = {}
    critical_paths = []
    
    # Check if target_id exists
    if target_id not in G:
        return [], [], 0.0

    # Initialize BFS queue with (node_id, current_risk_probability, path_taken)
    # The target service being migrated is assumed to have 100% (1.0) disruption/change state.
    queue = [(target_id, 1.0, [target_id])]
    impacted[target_id] = 1.0

    while queue:
        current, risk, path = queue.pop(0)
        
        # Traverse clients who depend on current
        for client in G.neighbors(current):
            if client in already_migrated:
                continue # Already successfully migrated, risk is zeroed
                
            edge = edge_map.get((current, client))
            if not edge:
                continue
                
            # Base attenuation based on criticality
            crit_factor = (
                constants.CRITICALITY_FACTOR_HIGH if edge.criticality == "High" 
                else (constants.CRITICALITY_FACTOR_MEDIUM if edge.criticality == "Medium" 
                else constants.CRITICALITY_FACTOR_LOW)
            )
            # Modifier based on protocol connection type
            type_mod = (
                constants.TYPE_MODIFIER_SYNC if edge.type == "Sync" 
                else (constants.TYPE_MODIFIER_DB if edge.type == "DB" 
                else constants.TYPE_MODIFIER_ASYNC_MQ)
            )
            
            # Propagated risk calculation
            new_risk = risk * crit_factor * type_mod
            new_risk = min(max(new_risk, 0.0), 1.0)
            
            # If the calculated risk is higher than previously recorded, update and queue
            if new_risk > 0.05 and new_risk > impacted.get(client, 0.0):
                impacted[client] = new_risk
                new_path = path + [client]
                critical_paths.append(new_path)
                queue.append((client, new_risk, new_path))

    # Construct the final impacted node list with updated risk probabilities
    impacted_nodes = []
    revenue_at_risk = 0.0
    
    for node in nodes:
        node_id = node.id
        # Skip the target node itself in the impacted list, as its migration is intentional
        if node_id == target_id:
            node_copy = node.model_copy()
            node_copy.failure_probability = 1.0
            node_copy.status = "Migrating"
            impacted_nodes.append(node_copy)
            revenue_at_risk += node.revenue_impact
            continue
            
        if node_id in impacted:
            node_copy = node.model_copy()
            node_copy.failure_probability = round(impacted[node_id], 2)
            node_copy.status = "Disrupted" if impacted[node_id] > 0.5 else "Degraded"
            impacted_nodes.append(node_copy)
            revenue_at_risk += node.revenue_impact * impacted[node_id]
        else:
            impacted_nodes.append(node)

    return impacted_nodes, critical_paths, round(revenue_at_risk, 2)

def run_monte_carlo(
    nodes: List[ServiceNode],
    impacted_nodes: List[ServiceNode],
    num_simulations: int = settings.MAX_SIMULATION_RUNS
) -> MonteCarloResult:
    """
    Performs a Monte Carlo simulation for migration duration and costs.
    Applies risk multipliers to base cost/duration.
    """
    # Create risk mapping
    risk_map = {n.id: n.failure_probability for n in impacted_nodes}
    
    durations = []
    costs = []
    
    for _ in range(num_simulations):
        total_duration = 0.0
        total_cost = 0.0
        
        for node in nodes:
            # Nominal base stats
            base_d = float(node.base_duration)
            base_c = float(node.base_cost)
            
            # Adjust ranges using failure probabilities as risk multipliers
            risk = risk_map.get(node.id, 0.0)
            
            # Risk impacts variability
            # Higher risk = longer duration & higher cost potential
            # triangular params: (min, mode, max)
            min_d = base_d * constants.MONTE_CARLO_MIN_DURATION_FACTOR
            mode_d = base_d * (1.0 + risk * 0.2)
            max_d = base_d * (constants.MONTE_CARLO_MAX_DURATION_BASE + risk * constants.MONTE_CARLO_MAX_DURATION_RISK_MULTIPLIER)
            
            min_c = base_c * constants.MONTE_CARLO_MIN_COST_FACTOR
            mode_c = base_c * (1.0 + risk * 0.3)
            max_c = base_c * (constants.MONTE_CARLO_MAX_COST_BASE + risk * constants.MONTE_CARLO_MAX_COST_RISK_MULTIPLIER)
            
            # Sample using triangular distribution
            sim_d = random.triangular(min_d, mode_d, max_d)
            sim_c = random.triangular(min_c, mode_c, max_c)
            
            total_duration += sim_d
            total_cost += sim_c
            
        durations.append(total_duration)
        costs.append(total_cost)
        
    durations_sorted = sorted(durations)
    costs_sorted = sorted(costs)
    
    # Percentiles
    p10_d = durations_sorted[int(num_simulations * 0.10)]
    p90_d = durations_sorted[int(num_simulations * 0.90)]
    
    p10_c = costs_sorted[int(num_simulations * 0.10)]
    p90_c = costs_sorted[int(num_simulations * 0.90)]
    
    mean_d = float(sum(durations) / len(durations))
    mean_c = float(sum(costs) / len(costs))
    
    # Generate points for charting CDF
    distribution = []
    # Take 20 steps to plot the S-curve
    for i in range(1, 100, 5):
        idx = int(num_simulations * (i / 100.0))
        distribution.append({
            "percentile": i,
            "duration": round(durations_sorted[idx], 1),
            "cost": round(costs_sorted[idx], 2)
        })
        
    return MonteCarloResult(
        confidence_90_duration=(round(p10_d, 1), round(p90_d, 1)),
        confidence_90_cost=(round(p10_c, 2), round(p90_c, 2)),
        expected_duration=round(mean_d, 1),
        expected_cost=round(mean_c, 2),
        distribution=distribution
    )
