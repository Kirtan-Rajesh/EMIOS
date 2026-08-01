"""Tests for the /api/v1 Report Snapshot module (generate / retrieve / feedback /
migration-plan).

Covers: 400 before the multi-agent planner has completed, happy path
generation (pulling in the 12-agent pipeline's waves/complexity/risk/cloud
readiness/recommendation output), retrieval, 404s, that regenerating upserts
rather than duplicating the stored snapshot, report feedback (simplified
human review), and final migration-plan generation (Bedrock-preferred LLM
pass, deterministic fallback in this test environment since no real provider
is configured).

The report is sourced from AgentRun.final_result - the persisted output of
the streaming 12-agent Master Orchestrator run (POST .../agent-runs/stream) -
not from the older single-target "what if" simulation/manually-posted waves,
so every test here seeds its assessment by running that pipeline to
completion first (see _create_assessment_with_agent_run)."""

import json

import pytest

pytestmark = pytest.mark.asyncio


async def _create_assessment(client) -> str:
    resp = await client.post(
        "/api/v1/assessments",
        json={"customer_name": "Acme", "project_name": "Proj", "target_cloud": "AWS"},
    )
    return resp.json()["data"]["assessment_id"]


_GRAPH_PAYLOAD = {
    "nodes": [
        {"id": "monolith", "name": "Monolith", "annual_cost": 200000.0},
        {"id": "auth_service", "name": "Auth Service", "annual_cost": 40000.0, "revenue_impact": 2000.0},
        {"id": "user_db", "name": "User DB", "type": "Database", "annual_cost": 80000.0},
    ],
    "edges": [
        {"source": "auth_service", "target": "monolith", "type": "Sync", "criticality": "High"},
        {"source": "auth_service", "target": "user_db", "type": "DB", "criticality": "High"},
    ],
}


async def _collect_planner_stream_events(client, assessment_id):
    events = []
    async with client.stream(
        "POST", f"/api/v1/assessments/{assessment_id}/agent-runs/stream"
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


async def _create_assessment_with_agent_run(client) -> str:
    """Seeds an assessment with a persisted, completed 12-agent pipeline run -
    the only thing generate_report() now reads from (see report_service.py)."""
    assessment_id = await _create_assessment(client)
    await client.post(f"/api/v1/assessments/{assessment_id}/graph", json=_GRAPH_PAYLOAD)
    events = await _collect_planner_stream_events(client, assessment_id)
    assert events[-1]["type"] == "complete"
    return assessment_id


async def test_generate_report_no_agent_run_yet(v1_client):
    assessment_id = await _create_assessment(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    assert response.status_code == 400
    assert response.json()["success"] is False


async def test_generate_report_nonexistent_assessment(v1_client):
    response = await v1_client.post("/api/v1/assessments/does-not-exist/report")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_generate_report_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["assessment_id"] == assessment_id
    assert isinstance(data["executive_summary"], str) and data["executive_summary"]
    assert 0.0 <= data["readiness_score"] <= 100.0
    assert isinstance(data["recommendations"], list) and len(data["recommendations"]) > 0
    assert isinstance(data["risk_summary"], dict)
    assert "category_scores" in data["risk_summary"]
    assert "generated_at" in data


async def test_generate_report_waves_come_from_pipeline_not_manual_post(v1_client):
    """migration_waves must reflect the 12-agent Migration Planner Agent's own
    output - a manually-POSTed MigrationWave row (the old, now-unrelated
    "wave override" surface) must have no bearing on the report."""
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/waves",
        json={"waves": [{"wave_number": 99, "components": ["nonexistent"], "rationale": "r", "risk_summary": "low"}]},
    )

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 201
    waves = response.json()["data"]["migration_waves"]
    assert len(waves) > 0
    assert all(w["wave_number"] != 99 for w in waves)
    all_components = {c for w in waves for c in w["components"]}
    assert "nonexistent" not in all_components
    # Real service names from the persisted graph, not raw ids.
    assert all_components <= {"Monolith", "Auth Service", "User DB"}


async def test_get_report_before_generation(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_get_report_after_generation(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["assessment_id"] == assessment_id


async def test_get_report_nonexistent_assessment(v1_client):
    response = await v1_client.get("/api/v1/assessments/does-not-exist/report")
    assert response.status_code == 404
    assert response.json()["success"] is False


async def test_regenerate_report_reflects_latest_planner_run(v1_client):
    """Rerunning the multi-agent planner and regenerating must pick up the new
    run's output (not the first run's), and bump the version rather than
    duplicating the stored snapshot."""
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    first = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    first_generated_at = first.json()["data"]["generated_at"]

    await _collect_planner_stream_events(v1_client, assessment_id)
    second = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert second.status_code == 201
    assert second.json()["data"]["current_version"] == 2
    assert second.json()["data"]["generated_at"] != first_generated_at

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report")
    assert response.json()["data"]["current_version"] == 2


async def test_submit_feedback_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/feedback",
        json={"rating": "up", "comment": "Looks solid, proceed."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["feedback_rating"] == "up"
    assert data["feedback_comment"] == "Looks solid, proceed."
    assert data["feedback_submitted_at"] is not None


async def test_submit_feedback_without_comment(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/feedback", json={"rating": "down"}
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["feedback_rating"] == "down"
    assert data["feedback_comment"] is None


async def test_submit_feedback_invalid_rating(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/feedback", json={"rating": "sideways"}
    )
    assert response.status_code == 422


async def test_submit_feedback_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/feedback", json={"rating": "up"}
    )
    assert response.status_code == 404


async def test_submit_feedback_nonexistent_assessment(v1_client):
    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/report/feedback", json={"rating": "up"}
    )
    assert response.status_code == 404


async def test_generate_migration_plan_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/migration-plan")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["final_migration_plan"] is not None
    assert isinstance(data["final_migration_plan"]["strategy"], str) and data["final_migration_plan"]["strategy"]
    assert data["final_plan_generated_at"] is not None


async def test_generate_migration_plan_includes_feedback(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/feedback",
        json={"rating": "down", "comment": "Wave 2 needs more testing first."},
    )

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/migration-plan")

    assert response.status_code == 201
    assert response.json()["data"]["final_migration_plan"] is not None


async def test_generate_migration_plan_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/migration-plan")
    assert response.status_code == 404


async def test_generate_migration_plan_nonexistent_assessment(v1_client):
    response = await v1_client.post("/api/v1/assessments/does-not-exist/migration-plan")
    assert response.status_code == 404


# --- Feedback-targeted revision + version history -------------------------
# No real LLM provider is configured in this test environment, so revise_report()
# always falls through to its deterministic fallback, which declares
# "executive_summary" as the changed section - see ReportService.revise_report().


async def test_generate_report_creates_version_one(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.json()["data"]["current_version"] == 1


async def test_revise_report_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/revise",
        json={"feedback": "Please call out the database migration risk more clearly."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["changed_sections"] == ["executive_summary"]
    assert data["current_version"] == 2
    assert "Feedback noted" in data["executive_summary"]


async def test_revise_report_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/revise", json={"feedback": "anything"}
    )
    assert response.status_code == 404


async def test_revise_report_nonexistent_assessment(v1_client):
    response = await v1_client.post(
        "/api/v1/assessments/does-not-exist/report/revise", json={"feedback": "anything"}
    )
    assert response.status_code == 404


async def test_revise_report_blank_feedback_rejected(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/revise", json={"feedback": ""}
    )
    assert response.status_code == 422


async def test_report_history_lists_versions_newest_first(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/revise", json={"feedback": "Tighten the summary."}
    )

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/history")

    assert response.status_code == 200
    versions = response.json()["data"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["source"] == "feedback"
    assert versions[0]["feedback_comment"] == "Tighten the summary."
    assert versions[1]["source"] == "generate"
    assert versions[1]["feedback_comment"] is None


async def test_report_history_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/history")
    assert response.status_code == 404


async def test_report_history_version_detail(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    first = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    first_summary = first.json()["data"]["executive_summary"]
    await v1_client.post(
        f"/api/v1/assessments/{assessment_id}/report/revise", json={"feedback": "Tighten the summary."}
    )

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/history/1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"] == 1
    assert data["executive_summary"] == first_summary


async def test_report_history_version_not_found(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/history/99")
    assert response.status_code == 404


# --- PDF export -------------------------------------------------------------


async def test_download_report_pdf_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"


async def test_download_report_pdf_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/report/pdf")
    assert response.status_code == 404


async def test_download_migration_plan_pdf_happy_path(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/migration-plan")

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/migration-plan/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"


async def test_download_migration_plan_pdf_before_plan_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)
    await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/migration-plan/pdf")
    assert response.status_code == 400


async def test_download_migration_plan_pdf_before_report_generated(v1_client):
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.get(f"/api/v1/assessments/{assessment_id}/migration-plan/pdf")
    assert response.status_code == 404


# --- LLM narrative pass (generate_report) ------------------------------------
# No real LLM provider is configured in this test environment (see conftest's
# _no_real_llm_credentials fixture), so generate_report()'s narrative pass
# always falls through to its deterministic fallback prose/recommendations -
# these confirm that fallback is still a well-formed, multi-part report on its
# own, and that the JSON-parsing path is exercised correctly when a provider
# *is* available (simulated here via monkeypatching invoke_with_fallback).


async def test_generate_report_fallback_narrative_without_llm(v1_client):
    """With zero LLM providers configured, generate_report() must still
    produce a non-empty executive_summary that cites the real computed
    numbers (not a blank/placeholder string) and a non-empty list of string
    recommendations - the deterministic safety net baked into
    ReportService._build_fallback_executive_summary()/_build_recommendations()."""
    assessment_id = await _create_assessment_with_agent_run(v1_client)

    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 201
    data = response.json()["data"]
    assert isinstance(data["executive_summary"], str)
    assert "Proj" in data["executive_summary"] and "Acme" in data["executive_summary"]
    assert isinstance(data["recommendations"], list) and len(data["recommendations"]) > 0
    assert all(isinstance(item, str) and item for item in data["recommendations"])


async def test_generate_report_uses_llm_narrative_when_configured(v1_client, monkeypatch):
    """Simulates a configured LLM provider by monkeypatching the
    invoke_with_fallback reference imported into report_service (patching
    app.core.llm_provider.invoke_with_fallback wouldn't take effect - that
    module-level import already bound the function by the time report_service
    is imported). A well-formed JSON response should flow straight through to
    the persisted report untouched, proving the JSON-with-code-fence-stripping
    parse path (mirroring revise_report()'s) works end to end."""
    import app.services_v1.report_service as report_service

    llm_summary = (
        "Paragraph one: current-state assessment. Paragraph two: key risks. "
        "Paragraph three: strategy comparison. Paragraph four: migration "
        "readiness narrative referencing the wave plan."
    )
    llm_recommendations = [
        "Stand up a blue/green cutover for User DB before touching Auth Service.",
        "Freeze schema changes on User DB for the two weeks preceding migration.",
        "Pre-provision target-cloud capacity sized for the recommended strategy's projected cost.",
        "Add automated rollback triggers keyed to the identified enterprise risks.",
    ]

    def _fake_invoke(system_prompt, user_prompt, agent_name, fallback_response, **kwargs):
        assert agent_name == "Report Narrative Agent"
        assert "Readiness score" in user_prompt  # real pipeline numbers reached the prompt
        return "```json\n" + json.dumps(
            {"executive_summary": llm_summary, "recommendations": llm_recommendations}
        ) + "\n```"

    monkeypatch.setattr(report_service, "invoke_with_fallback", _fake_invoke)

    assessment_id = await _create_assessment_with_agent_run(v1_client)
    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["executive_summary"] == llm_summary
    assert data["recommendations"] == llm_recommendations
    # Deterministic fields must stay untouched by the LLM pass.
    assert 0.0 <= data["readiness_score"] <= 100.0
    assert isinstance(data["migration_waves"], list) and len(data["migration_waves"]) > 0


async def test_generate_report_falls_back_on_malformed_llm_json(v1_client, monkeypatch):
    """A malformed (non-JSON) LLM response must not surface to the user - the
    deterministic fallback content should be persisted instead, exactly like
    the always-templated report used to be."""
    import app.services_v1.report_service as report_service

    monkeypatch.setattr(
        report_service, "invoke_with_fallback", lambda *a, **k: "not valid json at all"
    )

    assessment_id = await _create_assessment_with_agent_run(v1_client)
    response = await v1_client.post(f"/api/v1/assessments/{assessment_id}/report")

    assert response.status_code == 201
    data = response.json()["data"]
    assert isinstance(data["executive_summary"], str) and data["executive_summary"]
    assert "Proj" in data["executive_summary"]
    assert isinstance(data["recommendations"], list) and len(data["recommendations"]) > 0
