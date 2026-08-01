"""Business logic for the Report Snapshot module.

Compiles a report snapshot from an assessment's latest completed 12-agent
Master Orchestrator pipeline run (app.agents.workflow.run_full_assessment_stream,
persisted per-assessment by app/services_v1/agent_run_service.py as
AgentRun.final_result - see AgentRunRepository.get_latest_batch()). This
replaced an earlier design that sourced the report from a single manually-run,
single-target cascading-failure "what if" simulation
(app/services_v1/simulate_service.py) plus manually-posted migration waves
(app/services_v1/wave_service.py): that data answers "what breaks if I migrate
this one service", a different and narrower question than the whole-portfolio
readiness/strategy question this report exists to answer, and a rerun silently
replaced the prior result (one row per assessment) with no way to tell the
report was now stale. The 12-agent pipeline already computes migration waves
and a whole-portfolio strategy comparison, so the report is now consistent
with whatever the multi-agent planner produced last, and never depends on
whether/how many "what if" simulations were separately run.

readiness_score/risk_summary/migration_waves stay deterministic, explainable
math derived straight from the pipeline's Cloud Readiness/Risk Assessment/
Migration Planner agent outputs - but executive_summary/recommendations get an
LLM narrative pass on top of those numbers (Bedrock-preferred, see
app/core/llm_provider.py) so the report reads as a genuinely detailed writeup
rather than a templated one-liner. If no LLM provider is configured, or the
call fails, generate_report() falls back to the same deterministic prose it
used to always produce - the report is never worse than before.

Also owns the two later UML stages that build on the compiled report:
report feedback (simplified "human review" - a rating + optional comment, no
reviewer role or approval gating) and the final migration-plan generation
(one more LLM pass, Bedrock-preferred - see app/core/llm_provider.py).

Plus two additions on top of that compiled report:
  - revise_report(): a feedback-targeted LLM pass that revises only the
    section(s) (executive_summary/risk_summary/migration_waves/recommendations)
    the feedback concerns, leaving the rest untouched - every generate_report()
    or revise_report() call snapshots a new ReportRevision row so history can
    be listed/viewed (see _persist_new_version()).
  - generate_report_pdf(): renders the current report snapshot to PDF bytes.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import BadRequestException, ResourceNotFoundException
from app.core.llm_provider import invoke_with_fallback
from app.entities.assessment import Assessment
from app.entities.report import AssessmentReport, ReportRevision
from app.repositories.agent_run_repository import AgentRunRepository
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.report_repository import ReportRepository
from app.schemas_v1.report import REPORT_SECTIONS
from app.services_v1.graph_service import to_service_nodes
from app.services_v1.report_pdf import build_migration_plan_pdf, build_report_pdf

logger = logging.getLogger("emios")

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _valid_section_shape(section: str, value: Any) -> bool:
    """Guards against a malformed/hallucinated LLM update corrupting a field's
    expected shape (the frontend renders recommendations/migration_waves as
    lists, executive_summary as a paragraph, etc.) - an update failing this
    check is dropped rather than persisted."""
    if section == "executive_summary":
        return isinstance(value, str) and bool(value.strip())
    if section == "recommendations":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if section == "migration_waves":
        return isinstance(value, list)
    if section == "risk_summary":
        return isinstance(value, dict)
    return False


class ReportService:
    def __init__(
        self,
        report_repo: ReportRepository,
        agent_run_repo: AgentRunRepository,
        graph_repo: GraphRepository,
        assessment_repo: AssessmentRepository,
    ):
        self.report_repo = report_repo
        self.agent_run_repo = agent_run_repo
        self.graph_repo = graph_repo
        self.assessment_repo = assessment_repo

    async def _require_assessment(self, assessment_id: str) -> Assessment:
        assessment = await self.assessment_repo.get_by_id(assessment_id)
        if assessment is None:
            raise ResourceNotFoundException(f"Assessment '{assessment_id}' was not found.")
        return assessment

    async def _get_latest_pipeline_result(self, assessment_id: str) -> Optional[Dict[str, Any]]:
        """Mirrors AgentRunService.get_latest_result()'s "find the terminal row
        of the most recent batch" logic (kept here too rather than a
        cross-service call, matching this codebase's pattern of services
        sharing repositories directly - see e.g. ChatService) - returns the
        full structured output of the last completed 12-agent pipeline run for
        this assessment, or None if the planner has never completed one."""
        rows = await self.agent_run_repo.get_latest_batch(assessment_id)
        return next((r.final_result for r in reversed(rows) if r.final_result), None)

    async def _persist_new_version(
        self,
        assessment_id: str,
        content: Dict[str, Any],
        source: str,
        changed_sections: List[str],
        feedback_comment: Optional[str],
    ) -> AssessmentReport:
        """Upserts the report row with new content and appends a matching
        ReportRevision snapshot, bumping current_version. `content` must
        contain executive_summary/readiness_score/risk_summary/migration_waves/
        recommendations (the four report sections plus the deterministic score)."""
        existing = await self.report_repo.get_by_assessment(assessment_id)
        next_version = (existing.current_version if existing else 0) + 1

        values: Dict[str, Any] = dict(content)
        values["current_version"] = next_version
        if source == "generate":
            values["generated_at"] = datetime.now(timezone.utc)
        report = await self.report_repo.upsert(assessment_id, values)

        await self.report_repo.add_revision(
            report.id,
            {
                "version": next_version,
                "source": source,
                "executive_summary": content["executive_summary"],
                "readiness_score": content["readiness_score"],
                "risk_summary": content["risk_summary"],
                "migration_waves": content["migration_waves"],
                "recommendations": content["recommendations"],
                "changed_sections": changed_sections,
                "feedback_comment": feedback_comment,
            },
        )
        return report

    async def generate_report(self, assessment_id: str) -> AssessmentReport:
        assessment = await self._require_assessment(assessment_id)
        pipeline_result = await self._get_latest_pipeline_result(assessment_id)
        if pipeline_result is None:
            raise BadRequestException(
                f"The multi-agent planner has not been run yet for assessment '{assessment_id}'. "
                f"POST /api/v1/assessments/{assessment_id}/agent-runs/stream before generating a report."
            )

        nodes, _ = await self.graph_repo.get_graph(assessment_id)
        name_by_id = {n.id: n.name for n in to_service_nodes(nodes)}

        complexity = pipeline_result.get("complexity") or {}
        enterprise_risk = pipeline_result.get("enterprise_risk") or {}
        cloud_readiness = pipeline_result.get("cloud_readiness") or {}
        simulation_results = pipeline_result.get("simulation_results") or {}
        recommendation = pipeline_result.get("recommendation") or {}
        proposed_waves = pipeline_result.get("waves") or []
        decoupling_strategies = pipeline_result.get("decoupling_strategies") or []

        readiness_score = round(
            max(0.0, min(1.0, float(cloud_readiness.get("readiness_score", 0.0)))) * 100.0, 1
        )
        wave_dicts = self._build_wave_dicts(proposed_waves, decoupling_strategies, name_by_id)
        risk_summary = {
            "overall_risk_score": enterprise_risk.get("risk_score", 0.0),
            "category_scores": enterprise_risk.get("category_scores", {}),
            "top_risks": enterprise_risk.get("top_risks", []),
            "mitigation_strategies": enterprise_risk.get("mitigation_strategies", []),
        }

        fallback_recommendations = self._build_recommendations(recommendation, cloud_readiness, wave_dicts)
        fallback_executive_summary = self._build_fallback_executive_summary(
            assessment, complexity, enterprise_risk, recommendation, readiness_score
        )
        executive_summary, recommendations = await self._generate_narrative(
            assessment=assessment,
            complexity=complexity,
            enterprise_risk=enterprise_risk,
            cloud_readiness=cloud_readiness,
            recommendation=recommendation,
            simulation_results=simulation_results,
            wave_dicts=wave_dicts,
            readiness_score=readiness_score,
            fallback_executive_summary=fallback_executive_summary,
            fallback_recommendations=fallback_recommendations,
        )

        content: Dict[str, Any] = {
            "executive_summary": executive_summary,
            "readiness_score": readiness_score,
            "risk_summary": risk_summary,
            "migration_waves": wave_dicts,
            "recommendations": recommendations,
        }
        return await self._persist_new_version(
            assessment_id, content, source="generate", changed_sections=list(REPORT_SECTIONS), feedback_comment=None
        )

    @staticmethod
    def _build_wave_dicts(
        proposed_waves: List[List[str]],
        decoupling_strategies: List[Dict[str, Any]],
        name_by_id: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Adapts the Migration Planner Agent's `waves` (lists of node ids,
        grouped by topological order) into this report's
        `{wave_number, components, rationale, risk_summary}` shape - the same
        shape the old manually-POSTed MigrationWave rows used, so
        report_pdf.py/the frontend don't need to change. `risk_summary` per
        wave cites any decoupling strategy whose cycle touches a node in that
        wave, since those are the pipeline's own flagged cross-wave risks."""
        wave_dicts = []
        total = len(proposed_waves)
        for i, wave in enumerate(proposed_waves):
            components = [name_by_id.get(node_id, node_id) for node_id in wave]
            wave_node_set = set(wave)
            matching_strategies = [
                s for s in decoupling_strategies if wave_node_set.intersection(s.get("cycle", []))
            ]
            if matching_strategies:
                risk_summary = "; ".join(
                    s.get("recommendation") or s.get("description", "") for s in matching_strategies
                )
            else:
                risk_summary = "No circular-dependency violations flagged for this wave."
            wave_dicts.append(
                {
                    "wave_number": i + 1,
                    "components": components,
                    "rationale": f"Sequenced by topological dependency order (wave {i + 1} of {total}).",
                    "risk_summary": risk_summary,
                }
            )
        return wave_dicts

    async def get_report(self, assessment_id: str) -> AssessmentReport:
        await self._require_assessment(assessment_id)
        report = await self.report_repo.get_by_assessment(assessment_id)
        if report is None:
            raise ResourceNotFoundException(f"No report has been generated yet for assessment '{assessment_id}'.")
        return report

    async def submit_feedback(
        self, assessment_id: str, rating: str, comment: Optional[str]
    ) -> AssessmentReport:
        """UML Phase 8, simplified: records a thumbs up/down + optional comment
        against the existing report - no reviewer role, no approval gate."""
        await self.get_report(assessment_id)  # 404s if no report exists yet
        values: Dict[str, Any] = {
            "feedback_rating": rating,
            "feedback_comment": comment,
            "feedback_submitted_at": datetime.now(timezone.utc),
        }
        return await self.report_repo.upsert(assessment_id, values)

    async def revise_report(self, assessment_id: str, feedback: str) -> Tuple[AssessmentReport, List[str]]:
        """Feedback-targeted revision: asks the LLM which of REPORT_SECTIONS the
        feedback concerns and to revise only those, then persists a new version
        with just those sections changed. Returns (report, changed_sections)."""
        report = await self.get_report(assessment_id)  # 404s if no report exists yet

        system_prompt = (
            "You are the EMIOS Report Revision agent. You are given the current JSON content of "
            "a migration assessment report - executive_summary (string), risk_summary (object), "
            "migration_waves (array), and recommendations (array of strings) - plus human "
            "feedback requesting changes. Decide which of those four fields the feedback "
            "concerns, then return ONLY revised values for exactly those fields; do not modify "
            "or include fields the feedback did not ask about. Respond with strict JSON only, no "
            "markdown fences, in this exact shape: "
            '{"changed_sections": ["<field name>", ...], "updates": {"<field name>": <revised value>, ...}}'
        )
        user_prompt = (
            f"Current executive_summary: {report.executive_summary}\n"
            f"Current risk_summary: {json.dumps(report.risk_summary)}\n"
            f"Current migration_waves: {json.dumps(report.migration_waves)}\n"
            f"Current recommendations: {json.dumps(report.recommendations)}\n"
            f"Human feedback: {feedback}"
        )
        fallback_note = (
            f"{report.executive_summary}\n\n[Feedback noted: {feedback} - automatic AI revision "
            f"unavailable right now; manual review recommended.]"
        )
        fallback_json = json.dumps(
            {"changed_sections": ["executive_summary"], "updates": {"executive_summary": fallback_note}}
        )

        # invoke_with_fallback() makes a blocking LLM call (Bedrock/LangChain) - offload
        # to the threadpool so it doesn't stall the event loop for every other request.
        raw_output = await run_in_threadpool(
            invoke_with_fallback, system_prompt, user_prompt, "Report Revision Agent", fallback_json,
            assessment_id=assessment_id, trace_phase="report",
        )

        try:
            parsed: Dict[str, Any] = json.loads(_strip_code_fence(raw_output))
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Report revision LLM output was not valid JSON; falling back. Preview: {raw_output[:200]!r}")
            parsed = json.loads(fallback_json)

        declared_sections = [s for s in parsed.get("changed_sections", []) if s in REPORT_SECTIONS]
        raw_updates = parsed.get("updates") or {}
        updates = {
            section: raw_updates[section]
            for section in declared_sections
            if section in raw_updates and _valid_section_shape(section, raw_updates[section])
        }
        if not updates:
            # Malformed/empty LLM response even after code-fence stripping - use the
            # deterministic fallback so feedback is never silently dropped.
            fallback_parsed = json.loads(fallback_json)
            updates = fallback_parsed["updates"]

        content: Dict[str, Any] = {
            "executive_summary": updates.get("executive_summary", report.executive_summary),
            "readiness_score": report.readiness_score,  # deterministic - never LLM-revised
            "risk_summary": updates.get("risk_summary", report.risk_summary),
            "migration_waves": updates.get("migration_waves", report.migration_waves),
            "recommendations": updates.get("recommendations", report.recommendations),
        }
        updated_report = await self._persist_new_version(
            assessment_id, content, source="feedback", changed_sections=list(updates.keys()), feedback_comment=feedback
        )
        return updated_report, list(updates.keys())

    async def list_revisions(self, assessment_id: str) -> List[ReportRevision]:
        report = await self.get_report(assessment_id)  # 404s if no report exists yet
        return await self.report_repo.list_revisions(report.id)

    async def get_revision(self, assessment_id: str, version: int) -> ReportRevision:
        report = await self.get_report(assessment_id)  # 404s if no report exists yet
        revision = await self.report_repo.get_revision(report.id, version)
        if revision is None:
            raise ResourceNotFoundException(
                f"Version {version} was not found for assessment '{assessment_id}''s report."
            )
        return revision

    async def generate_migration_plan(self, assessment_id: str) -> AssessmentReport:
        """UML Phase 9: one more LLM pass (Bedrock-preferred) over the compiled
        report - and any feedback on it - to produce the final migration
        strategy. Not gated behind anything; callable any time a report exists."""
        assessment = await self._require_assessment(assessment_id)
        report = await self.get_report(assessment_id)

        system_prompt = (
            "You are the EMIOS Migration Strategy agent. Given a compiled migration "
            "assessment report and any human feedback on it, produce a concise, "
            "actionable final migration strategy: sequencing rationale, key risks to "
            "mitigate before each wave, and a clear go/no-go recommendation."
        )
        user_prompt = (
            f"Customer: {assessment.customer_name}, project: {assessment.project_name}, "
            f"target cloud: {assessment.target_cloud}\n"
            f"Executive summary: {report.executive_summary}\n"
            f"Readiness score: {report.readiness_score}/100\n"
            f"Risk summary: {json.dumps(report.risk_summary)}\n"
            f"Migration waves: {json.dumps(report.migration_waves)}\n"
            f"Recommendations: {json.dumps(report.recommendations)}\n"
            f"Human feedback: {report.feedback_rating or 'none'} - {report.feedback_comment or 'no comment'}"
        )
        wave_count = len(report.migration_waves or [])
        readiness_band = (
            "strong" if report.readiness_score >= 70 else "moderate" if report.readiness_score >= 40 else "low"
        )
        fallback = (
            f"Proceed with the {wave_count}-wave plan as sequenced. Readiness score of "
            f"{report.readiness_score}/100 indicates {readiness_band} readiness - address "
            f"flagged risks before Wave 1 begins."
        )

        # invoke_with_fallback() makes a blocking LLM call (Bedrock/LangChain) - offload
        # to the threadpool so it doesn't stall the event loop for every other request.
        strategy_text = await run_in_threadpool(
            invoke_with_fallback, system_prompt, user_prompt, "Migration Strategy Agent", fallback,
            assessment_id=assessment_id, trace_phase="report",
        )

        values: Dict[str, Any] = {
            "final_migration_plan": {"strategy": strategy_text},
            "final_plan_generated_at": datetime.now(timezone.utc),
        }
        return await self.report_repo.upsert(assessment_id, values)

    async def generate_report_pdf(self, assessment_id: str) -> bytes:
        assessment = await self._require_assessment(assessment_id)
        report = await self.get_report(assessment_id)
        # reportlab's document.build() is a blocking, CPU-bound call - offload to the
        # threadpool per this codebase's convention for blocking calls on the request path.
        return await run_in_threadpool(build_report_pdf, assessment, report)

    async def generate_migration_plan_pdf(self, assessment_id: str) -> bytes:
        assessment = await self._require_assessment(assessment_id)
        report = await self.get_report(assessment_id)
        if not report.final_migration_plan:
            raise BadRequestException(
                f"No final migration plan has been generated yet for assessment '{assessment_id}'. "
                f"POST /api/v1/assessments/{assessment_id}/migration-plan first."
            )
        pdf_bytes = await run_in_threadpool(build_migration_plan_pdf, assessment, report)
        return pdf_bytes

    async def _generate_narrative(
        self,
        *,
        assessment: Assessment,
        complexity: Dict[str, Any],
        enterprise_risk: Dict[str, Any],
        cloud_readiness: Dict[str, Any],
        recommendation: Dict[str, Any],
        simulation_results: Dict[str, Any],
        wave_dicts: List[dict],
        readiness_score: float,
        fallback_executive_summary: str,
        fallback_recommendations: List[str],
    ) -> Tuple[str, List[str]]:
        """LLM narrative pass over the deterministic metrics the 12-agent
        pipeline already computed (complexity/enterprise risk/cloud readiness/
        recommendation/simulation scenarios): asks for a detailed,
        multi-paragraph executive summary plus a richer set of concrete
        recommendations, both grounded in the real numbers passed in (never
        invented). Returns the LLM's (executive_summary, recommendations) if
        the call succeeds and the response parses/validates, else the
        deterministic fallback built by the caller - so the report is never
        worse than the old always-templated version, even with zero LLM
        providers configured."""
        system_prompt = (
            "You are the EMIOS Report Narrative agent. You are given deterministic, "
            "already-computed metrics from a completed 12-agent cloud migration "
            "assessment pipeline - treat every number as ground truth, never invent or "
            "contradict them. Your job is to turn those numbers into a genuinely "
            "detailed, well-organized executive report.\n\n"
            "Write an `executive_summary` of several paragraphs covering, in order: "
            "(1) a current-state assessment of the portfolio's complexity and migration "
            "readiness, (2) the key enterprise risks and what the risk/readiness scores "
            "imply, (3) how the competing migration strategies (lift & shift / replatform "
            "/ refactor) compare on cost, duration, and confidence, and (4) a "
            "migration-readiness narrative that references the wave sequencing plan if "
            "one is provided (or notes its absence if not).\n\n"
            "Also write `recommendations`: 4 to 8 concrete, specific, non-generic "
            "recommendations. Each one must be grounded in the actual numbers/waves/"
            "risks given (cite the relevant figure, wave, or strategy by name) - do not "
            "produce templated filler like 'proceed with caution'.\n\n"
            "Respond with strict JSON only, no markdown fences, in this exact shape: "
            '{"executive_summary": "<string>", "recommendations": ["<string>", ...]}'
        )
        user_prompt = (
            f"Project: '{assessment.project_name}' for customer '{assessment.customer_name}', "
            f"target cloud: {assessment.target_cloud}\n"
            f"Readiness score: {readiness_score}/100\n"
            f"Complexity: {json.dumps(complexity)}\n"
            f"Enterprise risk: {json.dumps(enterprise_risk)}\n"
            f"Cloud readiness: {json.dumps(cloud_readiness)}\n"
            f"Recommended strategy and rationale: {json.dumps(recommendation)}\n"
            f"Simulation scenarios by strategy: {json.dumps(simulation_results)}\n"
            f"Migration waves ({len(wave_dicts)} total): {json.dumps(wave_dicts)}"
        )
        fallback_json = json.dumps(
            {"executive_summary": fallback_executive_summary, "recommendations": fallback_recommendations}
        )

        # invoke_with_fallback() makes a blocking LLM call (Bedrock/LangChain) - offload
        # to the threadpool so it doesn't stall the event loop for every other request.
        raw_output = await run_in_threadpool(
            invoke_with_fallback, system_prompt, user_prompt, "Report Narrative Agent", fallback_json,
            assessment_id=assessment.id, trace_phase="report",
        )

        try:
            parsed: Dict[str, Any] = json.loads(_strip_code_fence(raw_output))
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Report narrative LLM output was not valid JSON; falling back. Preview: {raw_output[:200]!r}")
            parsed = json.loads(fallback_json)

        if not (
            _valid_section_shape("executive_summary", parsed.get("executive_summary"))
            and _valid_section_shape("recommendations", parsed.get("recommendations"))
        ):
            logger.warning("Report narrative LLM output had an unexpected shape; falling back to deterministic prose.")
            parsed = json.loads(fallback_json)

        return parsed["executive_summary"], parsed["recommendations"]

    @staticmethod
    def _build_fallback_executive_summary(
        assessment: Assessment,
        complexity: Dict[str, Any],
        enterprise_risk: Dict[str, Any],
        recommendation: Dict[str, Any],
        readiness_score: float,
    ) -> str:
        """The pre-LLM deterministic executive_summary, kept as the safety net
        _generate_narrative() falls back to when no LLM provider is configured
        or the call/parse fails - the report is never worse than before."""
        return (
            f"Assessment '{assessment.project_name}' for {assessment.customer_name} targeting "
            f"{assessment.target_cloud}: migration readiness {readiness_score}/100, overall "
            f"complexity score {complexity.get('complexity_score', 'N/A')}, enterprise risk score "
            f"{int(float(enterprise_risk.get('risk_score', 0.0)) * 100)}%. Recommended strategy: "
            f"{recommendation.get('recommended_strategy', 'N/A')} "
            f"({int(float(recommendation.get('confidence_score', 0.0)) * 100)}% confidence)."
        )

    @staticmethod
    def _build_recommendations(
        recommendation: Dict[str, Any], cloud_readiness: Dict[str, Any], wave_dicts: List[dict]
    ) -> List[str]:
        recommendations = []
        for key in (
            "engineering_recommendation",
            "business_recommendation",
            "modernization_recommendation",
            "customer_recommendation",
        ):
            value = recommendation.get(key)
            if value:
                recommendations.append(value)
        platform = cloud_readiness.get("recommended_platform")
        if platform:
            recommendations.append(f"Recommended target platform: {platform}, based on detected runtimes.")
        if not wave_dicts:
            recommendations.append(
                "No migration waves were produced by the last planner run - rerun the multi-agent "
                "planner before treating this readiness score as final."
            )
        if not recommendations:
            recommendations.append("No material recommendations available from the last planner run.")
        return recommendations
