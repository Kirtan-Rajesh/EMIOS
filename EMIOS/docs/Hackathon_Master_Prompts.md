# EMIOS Master Prompts

Use these prompts with a coding assistant after giving it the repository and
`docs/Hackathon_Execution_Log.md`. Each prompt requires a small, reviewable
change and tests; never ask an agent to rewrite the whole application.

## Universal engineering guardrails

```text
You are contributing to EMIOS, a hackathon-grade Enterprise Migration
Intelligence Platform. Read docs/Hackathon_Execution_Log.md first.

Preserve the zero-configuration demo path. Treat uploaded content as untrusted.
Do not add secrets, paid services, or a database requirement to run the demo.
Scores, estimates, and migration waves must be deterministic and evidence-backed;
an LLM may explain them but must not invent them. Make the smallest coherent
change, add or update tests, run relevant tests, and append a dated log entry
with files changed, contract changes, and test results. If the current tree has
unrelated edits, do not overwrite them.
```

## Lead architect — assessment spine

```text
[Universal guardrails]
Implement an Assessment Snapshot contract shared by the API and frontend.
Define typed models for assessment summary, assets, dependencies, findings,
scores, waves, scenarios, and provenance/evidence. Add one ABC Insurance fixture
that produces the same result offline. Expose a single GET endpoint returning
this snapshot after upload/reset. Do not redesign unrelated routes. Add unit and
API tests that prove IDs, required fields, and scores are stable.
```

## Discovery — safe ingestion

```text
[Universal guardrails]
Implement the discovery ingestion boundary. Support CSV and JSON inventory
fixtures with explicit file size/type validation, normalized asset/dependency
records, technology detection, warnings for duplicates/missing references, and
evidence references. Return structured validation errors rather than stack
traces. Add tests for valid input, duplicate IDs, malformed JSON, invalid edges,
and oversized/unsupported files. Do not call an LLM for parsing.
```

## Digital Twin — graph and evidence

```text
[Universal guardrails]
Implement a React Flow-ready adapter for the normalized assessment graph. Each
node must have stable type/color/label metadata, risk/readiness state, and an
evidence detail payload; each edge must preserve relationship type/criticality.
Add cycle and orphan indicators. Keep graph layout deterministic for the ABC
Insurance fixture and add tests for node/edge mapping.
```

## Assessment engine — deterministic math

```text
[Universal guardrails]
Implement pure deterministic functions for readiness, complexity, risk, effort,
and migration-wave sequencing. Return the formula inputs, assumptions and
evidence alongside every score. Dependencies must migrate no later than their
dependents; cycles must be surfaced with a decoupling recommendation. Add table-
driven unit tests including no assets, disconnected assets, cycle, and high-risk
database cases. Do not hide a random/LLM result behind a numeric score.
```

## AI/dashboard/report — explainable presentation

```text
[Universal guardrails]
Build the dashboard/report presentation from the Assessment Snapshot only.
Implement three deterministic scenarios (lift-and-shift, replatform, refactor),
highlight the recommendation, and show why with evidence, assumptions, and
confidence. If an LLM is configured, use it only to turn the supplied structured
facts into prose and validate its response shape; otherwise use a deterministic
template. Add UI/component tests or API mapping tests and a report smoke test.
```

## Test and release captain

```text
[Universal guardrails]
Make the test suite reproducible on Python 3.11. Separate core test/runtime
dependencies from optional model-provider/observability extras, pin compatible
versions, and document exact commands. Add a smoke test that exercises reset or
fixture upload → graph → simulation → plan → report with no cloud credentials.
Do not declare success until the command output is captured in the execution
log. Add a deployment smoke checklist and rollback/fallback instructions.
```
