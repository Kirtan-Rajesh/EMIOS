import json

import pytest
from fastapi.testclient import TestClient

from main import app
from app.agents.workflow import (
    run_full_assessment,
    digital_twin_agent,
    complexity_agent,
    cloud_readiness_agent,
    initialize_state_node,
)
from app.services.neo4j_service import get_demo_dataset


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_state():
    """A minimal AgentState dict for unit-testing individual pipeline nodes directly."""
    services = [
        {
            "id": "db", "name": "User DB", "type": "Database", "business_value": "High",
            "migration_complexity": "Medium", "base_cost": 50000.0, "base_duration": 30,
            "status": "Legacy", "failure_probability": 0.0, "runtime": "PostgreSQL 14",
            "annual_cost": 50000.0, "revenue_impact": 10000.0,
        },
        {
            "id": "service", "name": "User Service", "type": "Microservice", "business_value": "High",
            "migration_complexity": "Medium", "base_cost": 15000.0, "base_duration": 21,
            "status": "Legacy", "failure_probability": 0.0, "runtime": "Go 1.20",
            "annual_cost": 15000.0, "revenue_impact": 2000.0,
        },
        {
            "id": "monolith", "name": "Core Monolith", "type": "Monolith", "business_value": "Low",
            "migration_complexity": "High", "base_cost": 80000.0, "base_duration": 90,
            "status": "Legacy", "failure_probability": 0.0, "runtime": "COBOL/Java 8",
            "annual_cost": 80000.0, "revenue_impact": 5000.0,
        },
    ]
    dependencies = [
        {"source": "service", "target": "db", "type": "DB", "criticality": "High", "is_discovered": False},
        {"source": "monolith", "target": "service", "type": "Sync", "criticality": "High", "is_discovered": False},
    ]
    return {
        "services": services,
        "dependencies": dependencies,
        "proposed_waves": [],
        "negotiation_logs": [],
        "risk_assessment": {},
        "decoupling_strategies": [],
        "iterations": 0,
        "satisfied": False,
        "digital_twin": {},
        "migration_graph": {},
        "complexity": {},
        "enterprise_risk": {},
        "cloud_readiness": {},
        "simulation_results": {},
        "recommendation": {},
        "explainability": {},
        "report": {},
        "execution_history": [],
        "current_agent": "",
        "next_agent": "",
        "confidence_score": 0.0,
        "retry_counts": {},
        "workflow_status": "RUNNING",
        "status_reason": "",
    }


def test_digital_twin_agent_builds_react_flow_shape(sample_state):
    result = digital_twin_agent(sample_state)
    twin = result["digital_twin"]
    assert len(twin["nodes"]) == 3
    assert len(twin["edges"]) == 2
    assert twin["node_type_breakdown"]["Database"] == 1


def test_complexity_agent_derives_effort_and_team_size(sample_state):
    result = complexity_agent(sample_state)
    complexity = result["complexity"]
    assert 0.0 <= complexity["complexity_score"] <= 1.0
    assert set(complexity["dimension_scores"].keys()) == {
        "architecture", "business", "technology", "integration", "migration"
    }
    assert complexity["engineering_effort_days"] > 0
    assert complexity["team_size"] >= 2


def test_cloud_readiness_agent_recommends_a_known_platform(sample_state):
    sample_state["complexity"] = complexity_agent(sample_state)["complexity"]
    result = cloud_readiness_agent(sample_state)
    readiness = result["cloud_readiness"]
    assert 0.0 <= readiness["readiness_score"] <= 1.0
    assert readiness["recommended_platform"] in {"Azure", "AWS", "GoogleCloud"}


def test_initialize_state_node_seeds_defaults(sample_state):
    # Simulate a caller invoking the graph with only services/dependencies set.
    raw_state = {"services": sample_state["services"], "dependencies": sample_state["dependencies"]}
    result = initialize_state_node(raw_state)
    assert result["workflow_status"] == "RUNNING"
    assert result["complexity"] == {}
    assert result["retry_counts"] == {}


def test_run_full_assessment_end_to_end_on_demo_dataset():
    demo_nodes, demo_edges = get_demo_dataset()
    assert demo_nodes, "demo dataset fixture must be non-empty for this test to be meaningful"

    final_state = run_full_assessment(demo_nodes, demo_edges)

    assert final_state["workflow_status"] == "COMPLETED"

    executed_agents = {entry["agent"] for entry in final_state["execution_history"]}
    expected_agents = {
        "Initialize State", "Discovery Agent", "Dependency Analysis Agent", "Enterprise Digital Twin Agent",
        "Migration Intelligence Graph Agent", "Complexity Assessment Agent", "Risk Assessment Agent",
        "Cloud Readiness Agent", "Migration Planner Agent", "Simulation Agent",
        "Recommendation Agent", "Explainability Agent", "Report Generation Agent",
    }
    assert expected_agents.issubset(executed_agents)

    assert final_state["complexity"]["complexity_score"] is not None
    assert final_state["cloud_readiness"]["recommended_platform"] in {"Azure", "AWS", "GoogleCloud"}

    scenarios = final_state["simulation_results"]["scenarios"]
    assert set(scenarios.keys()) == {"Lift & Shift", "Replatform", "Refactor"}

    assert final_state["recommendation"]["recommended_strategy"] in scenarios
    assert "evidence" in final_state["explainability"]
    assert final_state["report"]["download_formats"]["json"]["status"] == "available"
    assert final_state["report"]["download_formats"]["pdf"]["status"] == "not_implemented"


def test_run_full_assessment_escalates_to_human_review_on_malformed_input():
    # Missing "name" on the service triggers a KeyError inside discovery_agent's
    # orphan-detection list comprehension - a real failure, not a data-quality flag.
    malformed_services = [{"id": "svc1"}]
    final_state = run_full_assessment(malformed_services, [])

    assert final_state["workflow_status"] == "HUMAN_REVIEW_REQUIRED"
    assert "Discovery Agent" in final_state["status_reason"]


def test_assess_endpoint_returns_full_report(client):
    sample_json = [
        {
            "component_id": "BillingService",
            "runtime": "Go 1.20",
            "downstream_dependencies": [],
            "business_criticality": "Critical",
            "annual_hosting_cost": 30000,
        }
    ]
    client.post(
        "/api/upload",
        files={"nodes_file": ("Sample_Input.json", json.dumps(sample_json).encode("utf-8"), "application/json")},
    )

    response = client.post("/api/assess")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("COMPLETED", "HUMAN_REVIEW_REQUIRED")
    assert "complexity" in data
    assert "recommendation" in data
    assert "simulation_results" in data
