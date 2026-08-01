"""Tests for LlmPromptExtractor's filename-citation filter
(app/services_v1/extraction/llm_prompt_extractor.py).

Regression coverage for a real extraction seen against the Northwind corpus:
a document that cited another source file by name ("see the 'Cloud
Readiness' field in Application_Inventory_Master.xlsx") got that citation
extracted as if it were an actual system. The prompt now tells the LLM not to
do this, but that alone isn't trustworthy (a small/fast model still did it) -
this is the deterministic backstop that makes it impossible regardless of
what the LLM returns.
"""

import json

from app.services_v1.extraction.llm_prompt_extractor import LlmPromptExtractor


def _extract_with_llm_response(monkeypatch, response: dict):
    # llm_prompt_extractor.py imports invoke_with_fallback eagerly at module
    # load time (`from app.core.llm_provider import invoke_with_fallback`),
    # unlike entity_resolution.py's lazy local imports - so it must be
    # patched where it's bound (this module), not at its origin, or the
    # patch has no effect on the already-imported name.
    monkeypatch.setattr(
        "app.services_v1.extraction.llm_prompt_extractor.invoke_with_fallback",
        lambda *a, **k: json.dumps(response),
    )
    extractor = LlmPromptExtractor()
    # .txt (not .docx/.pdf/...) so extract_text() takes the plain-decode
    # fallback path in DocumentProcessingService rather than trying to parse
    # this placeholder content as a real binary document format.
    return extractor.extract("Cloud_Readiness_Assessment.txt", b"irrelevant document text", "irrelevant preview")


def test_bare_filename_citation_is_filtered_out(monkeypatch):
    response = {
        "systems": [
            {"name": "NRG portfolio", "description": "Applications being assessed"},
            {"name": "Application Inventory Master.xlsx", "description": "Source of readiness data"},
        ],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    names = {n.name for n in result.nodes}
    assert names == {"NRG portfolio"}
    assert any("Application Inventory Master.xlsx" in w and "citation" in w for w in result.warnings)


def test_filename_citation_with_folder_path_is_filtered_out(monkeypatch):
    response = {
        "systems": [
            {"name": "02_Applications/Application_Inventory_Master.xlsx", "description": "cited source"},
            {"name": "Identity Platform SSO", "description": "real system"},
        ],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    names = {n.name for n in result.nodes}
    assert names == {"Identity Platform SSO"}


def test_various_document_extensions_are_filtered(monkeypatch):
    response = {
        "systems": [
            {"name": "Migration_Wave_Plan.xlsx"},
            {"name": "Network_Topology.docx"},
            {"name": "Runbook.pdf"},
            {"name": "Firewall_Rules.csv"},
            {"name": "Real System Name"},
        ],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    names = {n.name for n in result.nodes}
    assert names == {"Real System Name"}


def test_dependency_edge_referencing_a_filtered_system_is_dropped_not_crashed(monkeypatch):
    response = {
        "systems": [
            {"name": "Real System"},
            {"name": "Application_Inventory_Master.xlsx"},
        ],
        "dependencies": [
            {"source": "Real System", "target": "Application_Inventory_Master.xlsx"},
        ],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    # The filtered "system" never becomes a node, so the edge referencing it
    # has a dangling target - downstream merge_extraction_results() drops
    # dangling edges safely; this extractor itself must not crash building it.
    assert {n.name for n in result.nodes} == {"Real System"}


def test_system_name_that_merely_contains_a_dot_is_not_filtered(monkeypatch):
    """Precision check: don't over-match - a real system name that happens to
    contain a period (e.g. a version number) must survive."""
    response = {
        "systems": [{"name": "Node.js API Gateway"}],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    assert {n.name for n in result.nodes} == {"Node.js API Gateway"}


def test_cost_and_revenue_estimates_are_applied_to_the_node(monkeypatch):
    response = {
        "systems": [{"name": "Payments Service", "annual_cost": 120000, "revenue_impact": 85000}],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    node = next(n for n in result.nodes if n.name == "Payments Service")
    assert node.annual_cost == 120000.0
    assert node.revenue_impact == 85000.0


def test_malformed_cost_and_revenue_estimates_fall_back_to_zero_not_crash(monkeypatch):
    response = {
        "systems": [
            {"name": "Missing Figures"},
            {"name": "Bad Figures", "annual_cost": "not a number", "revenue_impact": -500},
        ],
        "dependencies": [],
        "agent_log": "test",
    }
    result = _extract_with_llm_response(monkeypatch, response)

    by_name = {n.name: n for n in result.nodes}
    assert by_name["Missing Figures"].annual_cost == 0.0
    assert by_name["Missing Figures"].revenue_impact == 0.0
    assert by_name["Bad Figures"].annual_cost == 0.0
    assert by_name["Bad Figures"].revenue_impact == 0.0
