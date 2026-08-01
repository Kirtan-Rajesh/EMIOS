"""Unit tests for app/agents/tools.py's search_schema_graph() - the tool given to
Bedrock-backed agents (discovery_agent in app/agents/workflow.py, ChatService.ask()
in app/services_v1/chat_service.py) via app.core.llm_provider.invoke_agentic()'s
tool_use loop. No LLM/network involved here - just the tool function itself.
"""

from app.agents.tools import search_schema_graph

SERVICES = [
    {"id": "svc-a", "name": "Order Service", "type": "Microservice", "business_value": "High", "migration_complexity": "Medium"},
    {"id": "svc-b", "name": "Orders Database", "type": "Database", "business_value": "High", "migration_complexity": "Low"},
    {"id": "svc-c", "name": "Notification Service", "type": "Microservice", "business_value": "Low", "migration_complexity": "Low"},
]
DEPENDENCIES = [
    {"source": "svc-a", "target": "svc-b", "type": "DB", "criticality": "High"},
]


def test_no_match_returns_clear_string_not_empty():
    result = search_schema_graph("nonexistent system", SERVICES, DEPENDENCIES)
    assert result
    assert "No documents or graph systems matched" in result
    assert "nonexistent system" in result


def test_matches_by_name_substring_case_insensitive():
    result = search_schema_graph("order", SERVICES, DEPENDENCIES)
    assert "Order Service" in result
    assert "Orders Database" in result
    assert "Notification Service" not in result


def test_filters_by_node_type():
    result = search_schema_graph("", SERVICES, DEPENDENCIES, node_type="Database")
    assert "Orders Database" in result
    assert "Order Service" not in result
    assert "Notification Service" not in result


def test_node_type_and_query_combine_as_and():
    result = search_schema_graph("order", SERVICES, DEPENDENCIES, node_type="Database")
    assert "Orders Database" in result
    assert "Order Service" not in result


def test_includes_dependency_counts():
    result = search_schema_graph("Order Service", SERVICES, DEPENDENCIES)
    assert "1 outbound / 0 inbound dependencies" in result


def test_no_assessment_id_skips_document_search_without_raising():
    # assessment_id="" (the default) means _search_document_chunks short-circuits
    # before touching embeddings/Qdrant at all - this should still work purely off
    # the graph match.
    result = search_schema_graph("order", SERVICES, DEPENDENCIES, assessment_id="")
    assert "Order Service" in result
    assert "Matching document excerpts" not in result


def test_empty_graph_and_no_assessment_id_returns_no_matches():
    result = search_schema_graph("anything", [], [], assessment_id="")
    assert "No documents or graph systems matched" in result


def test_document_search_failure_degrades_to_graph_only_result(monkeypatch):
    def _broken_get_embedding_provider():
        raise RuntimeError("embedding provider unavailable")

    import app.core.embeddings as embeddings_module

    monkeypatch.setattr(embeddings_module, "get_embedding_provider", _broken_get_embedding_provider)

    # Query matches a graph node by name, so the overall result should still surface
    # the graph match even though document search blew up internally.
    result = search_schema_graph("Order Service", SERVICES, DEPENDENCIES, assessment_id="assessment-1")
    assert "Order Service" in result
    assert "Matching document excerpts" not in result
