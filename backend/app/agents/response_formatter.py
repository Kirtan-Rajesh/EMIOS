"""Deterministic Markdown rendering for the 12-agent Master Orchestrator
pipeline's displayed output (app/agents/workflow.py) - the "mediator" between
each agent's raw data and the frontend.

Every agent in that pipeline computes its real structured output - scores,
per-service tables, wave sequences - in plain Python BEFORE ever calling an
LLM (see each agent function's body in workflow.py). The LLM call that
follows is used for exactly one thing: a short plain-English narrative
explaining what the data means and why it matters (see prompts.py's
"OUTPUT FORMAT" instruction, which asks for prose only - no JSON, no
Markdown).

That wasn't always true. Formatting used to be asked of the LLM itself, once
per agent, via a ~30-line rule block repeated across all 13 prompts. That
produced inconsistent results by construction: 13 independent LLM calls each
deciding on their own whether to tabulate, how much to bold, how verbose to
be - swinging between decorated ASCII-art walls of text and single clipped
sentences depending on the model and the day, and occasionally breaking the
JSON envelope it was also asked to produce (a malformed sibling field could
take down an otherwise-fine narrative - see _AGENT_LOG_FIELD_RE in
workflow.py for the salvage path that predates this file). Worse, that JSON
envelope was never even parsed for real data - only "agent_log" was ever
read - so asking for it at all was pure risk for zero benefit.

This module is the replacement: every agent's REAL Python data is rendered
into consistent Markdown by the same small set of functions below - one
narrative paragraph (from the LLM, plain prose), then a table for tabular
data, a bullet list for distinct findings, and (for the two genuinely
graph-shaped agents) a Mermaid flowchart - deterministically, so formatting
quality never depends on which model backs BEDROCK_LLM_MODEL_ID.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


# --- Generic rendering toolkit -------------------------------------------

def bold(value: Any) -> str:
    """Wraps a value in Markdown bold - for a key name/number inside a
    sentence this module constructs itself (never applied to LLM text,
    which is now asked to be plain prose)."""
    return f"**{value}**"


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Renders a GitHub-Flavored-Markdown table. Returns "" for no rows -
    callers should skip the section entirely rather than show a bare header."""
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def bullets(items: Sequence[str]) -> str:
    """Renders a tight Markdown bullet list. Returns "" for no items."""
    cleaned = [str(item) for item in items if item]
    return "\n".join(f"- {item}" for item in cleaned)


def compose(*sections: str) -> str:
    """Joins non-empty sections with a blank line between each - the
    boundary CommonMark actually requires for two adjacent blocks (a
    paragraph, then a table, then a list) to render as distinct elements
    instead of collapsing together."""
    return "\n\n".join(s.strip() for s in sections if s and s.strip())


def _mermaid_safe(name: Any) -> str:
    return str(name).replace('"', "'")


def mermaid_cycle_flowchart(cycle_names: Sequence[str]) -> str:
    """A closed-loop flowchart for one circular dependency chain, e.g.
    A -> B -> C -> A. Returns "" for a degenerate (<2 node) cycle."""
    if len(cycle_names) < 2:
        return ""
    node_ids = [f"n{i}" for i in range(len(cycle_names))]
    lines = ["flowchart LR"]
    for node_id, name in zip(node_ids, cycle_names):
        lines.append(f'    {node_id}["{_mermaid_safe(name)}"]')
    for i, node_id in enumerate(node_ids):
        lines.append(f"    {node_id} --> {node_ids[(i + 1) % len(node_ids)]}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def mermaid_wave_flowchart(waves: Sequence[Sequence[str]]) -> str:
    """A left-to-right flowchart of migration waves, each wave a subgraph of
    its member service names, wired Wave 1 -> Wave 2 -> ... in sequence.
    Returns "" for fewer than 2 waves (nothing sequential to show)."""
    if len(waves) < 2:
        return ""
    lines = ["flowchart LR"]
    for w_idx, members in enumerate(waves):
        lines.append(f'    subgraph W{w_idx}["Wave {w_idx + 1}"]')
        for m_idx, name in enumerate(members):
            lines.append(f'        w{w_idx}n{m_idx}["{_mermaid_safe(name)}"]')
        lines.append("    end")
    for w_idx in range(len(waves) - 1):
        lines.append(f"    W{w_idx} --> W{w_idx + 1}")
    return "```mermaid\n" + "\n".join(lines) + "\n```"


def score_row(label: str, score: float) -> List[Any]:
    """A (Dimension, Score) table row with the score rendered as a
    percentage - the shared shape every 0.0-1.0 score table below uses."""
    return [label, f"{round(score * 100)}%"]


# --- Per-agent formatters --------------------------------------------------
# Each takes the plain-prose LLM narrative plus the exact data the calling
# agent function in workflow.py already computed - no re-derivation, no
# re-parsing, just rendering.

def format_discovery(narrative: str, orphans: List[str], shared_db_findings: List[str]) -> str:
    parts = [narrative]
    if orphans:
        parts.append(f"{bold('Orphaned services')} (no declared connections):\n" + bullets(orphans))
    if shared_db_findings:
        parts.append(bullets(shared_db_findings))
    return compose(*parts)


def format_dependency(narrative: str, decoupling_strategies: List[Dict[str, Any]]) -> str:
    parts = [narrative]
    for i, strat in enumerate(decoupling_strategies):
        cycle_names = strat.get("cycle_names") or strat.get("cycle", [])
        flowchart = mermaid_cycle_flowchart(cycle_names)
        if flowchart:
            parts.append(flowchart)
        parts.append(
            f"{bold(f'Cycle {i + 1}')}: {strat.get('description', '')} "
            f"{bold('Recommendation')}: {strat.get('recommendation', '')}"
        )
    return compose(*parts)


def format_planner(narrative: str, waves_named: List[List[str]], adjustments: List[str]) -> str:
    parts = [narrative]
    flowchart = mermaid_wave_flowchart(waves_named)
    if flowchart:
        parts.append(flowchart)
    elif waves_named:
        rows = [[f"Wave {i + 1}", ", ".join(members)] for i, members in enumerate(waves_named)]
        parts.append(table(["Wave", "Services"], rows))
    if adjustments:
        parts.append(f"{bold('Adjustments made')}:\n" + bullets(adjustments))
    return compose(*parts)


def format_risk(narrative: str, risk_assessment: Dict[str, Dict[str, Any]], name_by_id: Dict[str, str], objections: List[str]) -> str:
    parts = [narrative]
    rows = [
        [name_by_id.get(sid, sid), f"{round(v.get('score', 0.0) * 100)}%", v.get("complexity", "")]
        for sid, v in risk_assessment.items()
    ]
    if rows:
        parts.append(table(["Service", "Risk", "Complexity"], rows))
    if objections:
        parts.append(f"{bold('Objections raised')}:\n" + bullets(objections))
    return compose(*parts)


def format_digital_twin(narrative: str, node_type_breakdown: Dict[str, int]) -> str:
    rows = [[t, c] for t, c in node_type_breakdown.items() if c > 0]
    return compose(narrative, table(["Type", "Count"], rows))


def format_migration_graph(narrative: str, entities: Dict[str, List[Any]], decoupling_strategy_count: int) -> str:
    rows = [
        ["Applications", len(entities.get("applications", []))],
        ["Databases", len(entities.get("databases", []))],
        ["Queues / ETL edges", len(entities.get("queues_or_etl", []))],
        ["External systems", len(entities.get("external_systems", []))],
    ]
    parts = [narrative, table(["Entity type", "Count"], rows)]
    if decoupling_strategy_count:
        parts.append(f"{decoupling_strategy_count} decoupling strategy(ies) folded into these graph relationships.")
    return compose(*parts)


def format_complexity(narrative: str, dimension_scores: Dict[str, float], engineering_effort_days: int, estimated_timeline_weeks: int, team_size: int) -> str:
    rows = [score_row(dim.replace("_", " ").title(), score) for dim, score in dimension_scores.items()]
    summary = (
        f"{bold('Estimated effort')}: {engineering_effort_days} person-days over "
        f"~{estimated_timeline_weeks} weeks with a team of {team_size}."
    )
    return compose(narrative, table(["Dimension", "Score"], rows), summary)


def format_enterprise_risk(narrative: str, category_scores: Dict[str, float], top_risks: List[str], mitigation_strategies: List[str]) -> str:
    rows = [score_row(cat.replace("_", " ").title(), score) for cat, score in category_scores.items()]
    parts = [narrative, table(["Risk category", "Score"], rows)]
    if top_risks:
        parts.append(f"{bold('Top risks')}:\n" + bullets(top_risks))
    if mitigation_strategies:
        parts.append(f"{bold('Mitigations')}:\n" + bullets(mitigation_strategies))
    return compose(*parts)


def format_cloud_readiness(narrative: str, platform_scores: Dict[str, float], recommended_platform: str) -> str:
    rows = [
        [f"{bold(p)} (recommended)" if p == recommended_platform else p, f"{round(s * 100)}%"]
        for p, s in platform_scores.items()
    ]
    return compose(narrative, table(["Platform", "Readiness"], rows))


def format_simulation(narrative: str, scenarios: Dict[str, Dict[str, Any]]) -> str:
    rows = [
        [
            strategy,
            f"{round(res.get('risk', 0.0) * 100)}%",
            f"{res.get('duration_days', 0)}d",
            f"${res.get('cost_usd', 0):,.0f}",
            f"{round(res.get('confidence', 0.0) * 100)}%",
        ]
        for strategy, res in scenarios.items()
    ]
    return compose(narrative, table(["Strategy", "Risk", "Duration", "Cost", "Confidence"], rows))


def format_recommendation(narrative: str, recommended_strategy: str, confidence_score: float, engineering_recommendation: str, business_recommendation: str, modernization_recommendation: str, customer_recommendation: str) -> str:
    headline = f"{bold('Recommended strategy')}: {bold(recommended_strategy)} ({round(confidence_score * 100)}% confidence)"
    recs = bullets(
        [
            f"{bold('Engineering')}: {engineering_recommendation}",
            f"{bold('Business')}: {business_recommendation}",
            f"{bold('Modernization')}: {modernization_recommendation}",
            f"{bold('Customer-facing')}: {customer_recommendation}",
        ]
    )
    return compose(narrative, headline, recs)


def format_explainability(narrative: str, evidence: List[str], risks_considered: List[str], confidence_explanation: str) -> str:
    parts = [narrative]
    if evidence:
        parts.append(f"{bold('Evidence considered')}:\n" + bullets(evidence))
    if risks_considered:
        parts.append(f"{bold('Risks considered')}:\n" + bullets(risks_considered))
    parts.append(confidence_explanation)
    return compose(*parts)


def format_report(narrative: str, total_services: int, total_dependencies: int, wave_count: int, recommended_strategy: str, confidence_score: float) -> str:
    stats = bullets(
        [
            f"{bold(total_services)} services and {bold(total_dependencies)} dependencies assessed across {bold(wave_count)} migration wave(s).",
            f"Recommended strategy: {bold(recommended_strategy)} ({round(confidence_score * 100)}% confidence).",
        ]
    )
    return compose(narrative, stats)
