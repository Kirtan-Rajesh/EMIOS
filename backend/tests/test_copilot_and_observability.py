import pytest
import json
from fastapi.testclient import TestClient
from main import app
from app.agents import prompts
from app.core import observability


@pytest.fixture
def client():
    return TestClient(app)

def test_prompt_rendering():
    sys_prompt = prompts.DISCOVERY_AGENT_SYSTEM_PROMPT
    assert "Discovery Agent" in sys_prompt
    
    usr_prompt = prompts.DISCOVERY_AGENT_USER_PROMPT.format(
        service_count=2,
        services_json="[]",
        dependency_count=1,
        dependencies_json="[]"
    )
    assert "Analyze the following enterprise system topology" in usr_prompt

def test_observability_endpoint(client):
    response = client.get("/api/observability/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "langfuse_host" in data
    assert "metrics" in data

def test_copilot_chat_endpoint(client):
    payload = {
        "messages": [
            {"role": "user", "content": "What is the annual hosting cost of the monolith?"}
        ]
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert len(data["reply"]) > 0

def test_mandatory_llm_planner_tracing(client):
    response = client.post("/api/plan")
    assert response.status_code == 200
    data = response.json()
    assert "waves" in data
    assert "trace_id" in data
    assert data["trace_id"] is not None
