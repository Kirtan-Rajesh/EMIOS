import pytest
import json
from fastapi.testclient import TestClient
from main import app

@pytest.fixture
def client():
    """Provides a TestClient for FastAPI route testing."""
    return TestClient(app)

def test_health_check_endpoint(client):
    # Act
    response = client.get("/api/health")
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert data["api"] == "online"

def test_upload_json_ingestion(client):
    # Arrange
    sample_json = [
        {
            "component_id": "BillingService",
            "runtime": "Go 1.20",
            "downstream_dependencies": ["DatabaseX"],
            "business_criticality": "Critical",
            "annual_hosting_cost": 30000
        }
    ]
    json_bytes = json.dumps(sample_json).encode("utf-8")
    
    # Act
    response = client.post(
        "/api/upload",
        files={"nodes_file": ("Sample_Input.json", json_bytes, "application/json")}
    )
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["parsed_nodes_count"] >= 1

def test_simulation_endpoint(client):
    # Arrange
    # Initialize some data first
    sample_json = [
        {
            "component_id": "BillingService",
            "runtime": "Go 1.20",
            "downstream_dependencies": [],
            "business_criticality": "Critical",
            "annual_hosting_cost": 30000
        }
    ]
    client.post("/api/upload", files={"nodes_file": ("Sample_Input.json", json.dumps(sample_json).encode("utf-8"), "application/json")})
    
    # Act
    payload = {"target_id": "BillingService", "already_migrated": []}
    response = client.post("/api/simulate", json=payload)
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "revenue_at_risk" in data
    assert "monte_carlo" in data
    assert data["total_hosting_cost"] == 30000.0

def test_planner_endpoint(client):
    # Arrange
    sample_json = [
        {
            "component_id": "BillingService",
            "runtime": "Go 1.20",
            "downstream_dependencies": [],
            "business_criticality": "Critical",
            "annual_hosting_cost": 30000
        }
    ]
    client.post("/api/upload", files={"nodes_file": ("Sample_Input.json", json.dumps(sample_json).encode("utf-8"), "application/json")})
    
    # Act
    response = client.post("/api/plan")
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "waves" in data
    assert len(data["waves"]) > 0

def test_csv_validation_report(client):
    # CSV content with duplicate systems and invalid target links to test validation logging
    nodes_csv = (
        "System ID,System Name,Category,Priority,Monthly Revenue ($)\n"
        "auth_service,Auth Service,Microservice,High,10000.0\n"
        "auth_service,Duplicate Auth,Microservice,Low,5000.0\n"
    )
    edges_csv = (
        "From System,To System,Connection Type,Importance\n"
        "auth_service,non_existent,Sync,High\n"
        "auth_service,auth_service,Sync,High\n"
    )
    
    response = client.post(
        "/api/upload",
        files={
            "nodes_file": ("nodes.csv", nodes_csv.encode("utf-8"), "text/csv"),
            "edges_file": ("edges.csv", edges_csv.encode("utf-8"), "text/csv")
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["parsed_nodes_count"] == 1  # 1 because duplicate got overwritten
    assert data["parsed_edges_count"] == 0  # 0 because invalid target and self-loop got skipped
    assert len(data["warnings"]) >= 3
    assert "Duplicate Node ID" in data["warnings"][0]
    assert "references non-existent target" in data["warnings"][1] or "does not exist in nodes CSV" in data["warnings"][1]
    assert "Self-referential connection skipped" in data["warnings"][2]

def test_template_download(client):
    response = client.get("/api/templates/download")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data

