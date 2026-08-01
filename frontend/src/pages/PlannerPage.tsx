import { Component, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import {
  AlertTriangle,
  FileText,
  GitBranch,
  Lightbulb,
  Loader2,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { Card } from "@/components/Card";
import { InfoBanner } from "@/components/InfoBanner";
import { Markdown } from "@/components/Markdown";
import { Badge, RECOMMENDATION_FIELDS, ScoreBar, titleCase, toneForScore } from "@/components/pipeline-metrics";
import { Button } from "@/components/ui/button";
import { agentLogSource, agentRawMessage, tryParseAgentOutput } from "@/lib/agent-output";
import { v1Api } from "@/lib/api";
import { usePlannerRun } from "@/lib/planner-run-context";
import type {
  AgentRunResponse,
  AssessmentGraphResponse,
  DependencyAgentOutput,
  DiscoveryAgentOutput,
  PlannerAgentOutput,
  RecommendationAgentOutput,
  ReportGenerationAgentOutput,
  RiskAgentOutput,
  RunPlannerResponse,
} from "@/types/api";

/** Renders the 12-agent Master Orchestrator pipeline's computed metrics still
 * shown on Wave Planner: overall confidence and Explainability, side by side.
 * Complexity/Enterprise risk/Cloud readiness moved to the Overview page
 * (alongside its other whole-system KPIs); Simulation scenarios and
 * Recommendation moved to the What-If Simulation page - see
 * components/pipeline-metrics.tsx for all of those. Absent for runs from the
 * legacy 4-agent run_planner() path, so each card only renders when its data
 * is actually present. */
export function PipelineMetricsSection({ result }: { result: RunPlannerResponse }) {
  const { explainability, confidence_score: confidenceScore } = result;

  if (!explainability && confidenceScore === undefined) return null;

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Pipeline metrics</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {confidenceScore !== undefined && (
          <Card className="p-5">
            <h3 className="mb-3 font-medium text-foreground">Overall confidence</h3>
            <ScoreBar
              label="Pipeline confidence"
              value={confidenceScore}
              tone={toneForScore(confidenceScore, "higher-is-better")}
              size="lg"
            />
          </Card>
        )}

        {explainability && (
          <Card className="p-5">
            <h3 className="mb-3 font-medium text-foreground">Explainability</h3>
            {explainability.confidence_explanation && (
              <p className="mb-3 text-sm leading-relaxed text-foreground/80">{explainability.confidence_explanation}</p>
            )}
            {!!explainability.evidence?.length && (
              <div className="mb-3">
                <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Evidence</p>
                <ul className="list-inside list-disc space-y-1.5 text-sm leading-relaxed text-foreground/80">
                  {explainability.evidence.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!explainability.dependencies_considered?.length && (
              <div className="mb-3">
                <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">
                  Dependencies considered
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {explainability.dependencies_considered.map((d) => (
                    <Badge key={d} tone="slate">
                      {d}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
            {!!explainability.risks_considered?.length && (
              <div>
                <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Risks considered</p>
                <div className="flex flex-wrap gap-1.5">
                  {explainability.risks_considered.map((r) => (
                    <Badge key={r} tone="amber">
                      {r}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

/** Renders arbitrary parsed JSON as nested label/value rows instead of a raw
 * blob - used when an agent's message doesn't match one of the four known
 * output shapes below (a schema change, a new agent type, or a model that
 * added/renamed a field), so the UI still reads as prose-ish structure
 * instead of a wall of braces and quotes. */
function FormattedValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">—</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">None</span>;
    if (value.every((v) => v === null || typeof v !== "object")) {
      return (
        <ul className="list-inside list-disc space-y-0.5">
          {value.map((v, i) => (
            <li key={i}>{String(v)}</li>
          ))}
        </ul>
      );
    }
    return (
      <div className="space-y-2">
        {value.map((v, i) => (
          <div key={i} className="rounded-md border border-border/60 p-2">
            <FormattedValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-muted-foreground">None</span>;
    return (
      <div className="space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex flex-wrap gap-x-1.5 gap-y-0.5 text-xs">
            <span className="shrink-0 font-medium text-foreground">{titleCase(k)}:</span>
            <span className="text-foreground/80">
              <FormattedValue value={v} />
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  return <span>{String(value)}</span>;
}

/** Fallback for whenever an agent's message doesn't parse into its expected
 * typed shape (tryParseAgentOutput returned null) - if it's valid JSON of a
 * different shape, format it generically rather than dumping raw text; only
 * genuinely non-JSON prose falls through to a plain paragraph. */
function RawMessage({ text }: { text: string }) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = undefined;
  }
  if (parsed !== undefined && parsed !== null && typeof parsed === "object") {
    return (
      <div className="text-sm text-foreground/80">
        <FormattedValue value={parsed} />
      </div>
    );
  }
  return <Markdown text={text} className="text-muted-foreground" />;
}

/** A small/fast model occasionally drifts from the exact schema its prompt
 * asked for (a field present but the wrong type, an extra/missing nesting
 * level) - tryParseAgentOutput can't catch that in advance since it only
 * checks "is this an object", not each field's shape. Rather than one bad
 * field crashing this whole card (and, without an error boundary, the rest
 * of the page below it), catch it here and fall back to RawMessage so the
 * agent's raw text is still shown instead of a blank/broken panel. */
class ExplainerBoundary extends Component<{ fallbackText: string; children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Agent explainer failed to render structured output; falling back to raw text.", error);
  }

  render() {
    if (this.state.hasError) return <RawMessage text={this.props.fallbackText} />;
    return this.props.children;
  }
}

/** Every agent's system prompt asks for this as a "formatted narrative log
 * for human architects", but it's typed as optional and previously never
 * rendered anywhere - shown as a lead-in narrative paragraph above whatever
 * structured badges/lists follow. */
function AgentLog({ text }: { text?: string }) {
  if (!text) return null;
  return <Markdown text={text} />;
}

function DiscoveryExplainer({ rawText }: { rawText: string }) {
  const output = tryParseAgentOutput<DiscoveryAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  return (
    <div className="space-y-3">
      {output.summary && <Markdown text={output.summary} className="text-foreground/80" />}
      {!!output.orphans_found?.length && (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">
            Orphan components flagged for review
          </p>
          <div className="flex flex-wrap gap-2">
            {output.orphans_found.map((o) => (
              <Badge key={o} tone="amber">
                {o}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {!!output.shared_databases?.length && (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Shared-database risk</p>
          <div className="space-y-2">
            {output.shared_databases.map((db) => (
              <div
                key={db.database_id}
                className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-sm leading-relaxed text-foreground/80"
              >
                <span className="font-medium text-foreground">{db.database_id}</span> accessed by{" "}
                {Array.isArray(db.accessed_by) ? db.accessed_by.join(", ") : String(db.accessed_by ?? "")}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Renders one decoupling strategy's cycle as "A → B → A" - defensively,
 * since `cycle` is model-generated and occasionally arrives as something
 * other than a clean 2+-element array (a string, a single-element array,
 * etc.), which would otherwise throw (no `.join` on a string) or silently
 * print "undefined" (indexing past a short array). */
function formatCycle(cycle: unknown): string {
  if (!Array.isArray(cycle) || cycle.length === 0) return String(cycle ?? "");
  const names = cycle.map((c) => String(c));
  return names.length > 1 ? `${names.join(" → ")} → ${names[0]}` : names[0];
}

function DependencyExplainer({ rawText }: { rawText: string }) {
  const output = tryParseAgentOutput<DependencyAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  return (
    <div className="space-y-3">
      <AgentLog text={output.agent_log} />
      <div className="flex items-center gap-2 text-sm text-foreground/80">
        <GitBranch className="h-4 w-4 text-destructive dark:text-[#FF204E]" />
        {output.cycles_detected_count ?? 0} circular dependenc
        {output.cycles_detected_count === 1 ? "y" : "ies"} detected
      </div>
      {!!output.decoupling_strategies?.length &&
        output.decoupling_strategies.map((s, i) => (
          <div key={i} className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm leading-relaxed dark:border-[#FF204E]/20 dark:bg-[#FF204E]/5">
            <p className="mb-1.5 font-medium text-foreground">{formatCycle(s?.cycle)}</p>
            <p className="mb-2 text-foreground/80">{s?.description}</p>
            {s?.recommendation && (
              <p className="flex items-start gap-1.5 text-[#ff6f92]">
                <Lightbulb className="mt-1 h-3.5 w-3.5 shrink-0" /> {s.recommendation}
              </p>
            )}
          </div>
        ))}
    </div>
  );
}

function RiskExplainer({ rawText }: { rawText: string }) {
  const output = tryParseAgentOutput<RiskAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  const assessmentEntries = Object.entries(output.risk_assessment ?? {});
  return (
    <div className="space-y-3">
      <AgentLog text={output.agent_log} />
      {output.risk_threshold_exceeded !== undefined && (
        <Badge tone={output.risk_threshold_exceeded ? "rose" : "emerald"}>
          {output.risk_threshold_exceeded ? "Risk threshold exceeded" : "Within risk threshold"}
        </Badge>
      )}
      {!!output.objections?.length && (
        <ul className="space-y-2">
          {output.objections.map((obj, i) => (
            <li key={i} className="flex items-start gap-2 text-sm leading-relaxed text-foreground/80">
              <AlertTriangle className="mt-1 h-3.5 w-3.5 shrink-0 text-destructive" />
              {obj}
            </li>
          ))}
        </ul>
      )}
      {assessmentEntries.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-3 font-medium">Service</th>
                <th className="py-1 pr-3 font-medium">Risk score</th>
                <th className="py-1 font-medium">Complexity</th>
              </tr>
            </thead>
            <tbody>
              {assessmentEntries.map(([svc, entry]) => (
                <tr key={svc} className="border-t border-border/50">
                  <td className="py-1.5 pr-3 text-foreground">{svc}</td>
                  <td className="py-1.5 pr-3 text-foreground/80">{Math.round(entry.score * 100)}%</td>
                  <td className="py-1.5 text-foreground/80">{entry.complexity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PlannerExplainer({ rawText, nameById }: { rawText: string; nameById: Map<string, string> }) {
  const output = tryParseAgentOutput<PlannerAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  return (
    <div className="space-y-3">
      <AgentLog text={output.agent_log} />
      {!!output.waves?.length && (
        <ol className="list-inside list-decimal space-y-1 text-sm text-foreground/80">
          {output.waves.map((wave, i) => (
            <li key={i}>
              <span className="text-foreground">Wave {i + 1}:</span>{" "}
              {wave.map((componentId) => nameById.get(componentId) ?? componentId).join(", ")}
            </li>
          ))}
        </ol>
      )}
      {!!output.adjustments_made?.length && (
        <ul className="list-inside list-disc space-y-1.5 text-sm leading-relaxed text-foreground/80">
          {output.adjustments_made.map((a, i) => (
            <li key={i}>{a}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecommendationExplainer({ rawText }: { rawText: string }) {
  const output = tryParseAgentOutput<RecommendationAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  return (
    <div className="space-y-3">
      <AgentLog text={output.agent_log} />
      <div className="flex flex-wrap items-center gap-2">
        {output.recommended_strategy && <Badge tone="emerald">{output.recommended_strategy}</Badge>}
        {output.confidence_score !== undefined && (
          <span className="text-xs text-muted-foreground">
            {Math.round(output.confidence_score * 100)}% confidence
          </span>
        )}
      </div>
      <div className="space-y-2.5">
        {RECOMMENDATION_FIELDS.filter(({ key }) => output[key as keyof RecommendationAgentOutput]).map(
          ({ key, label }) => (
            <div key={key} className="rounded-lg border border-border bg-muted/20 p-3">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
              <p className="text-sm leading-relaxed text-foreground/80">
                {output[key as keyof RecommendationAgentOutput] as string}
              </p>
            </div>
          ),
        )}
      </div>
    </div>
  );
}

function ReportGenerationExplainer({ rawText }: { rawText: string }) {
  const output = tryParseAgentOutput<ReportGenerationAgentOutput>(rawText);
  if (!output) return <RawMessage text={rawText} />;
  return (
    <div className="space-y-3">
      {output.executive_summary && <Markdown text={output.executive_summary} className="text-foreground/80" />}
      {!!output.key_takeaways?.length && (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Key takeaways</p>
          <ul className="list-inside list-disc space-y-1 text-sm text-foreground/80">
            {output.key_takeaways.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
      <AgentLog text={output.agent_log} />
    </div>
  );
}

const AGENT_ICON: Record<string, ComponentType<{ className?: string }>> = {
  "Discovery Agent": Sparkles,
  "Dependency Agent": GitBranch,
  "Risk Agent": ShieldAlert,
  "Planner Agent": Lightbulb,
  "Recommendation Agent": TrendingUp,
  "Report Generation Agent": FileText,
};

const KNOWN_AGENT_TYPES = [
  "Discovery Agent",
  "Dependency Agent",
  "Risk Agent",
  "Planner Agent",
  "Recommendation Agent",
  "Report Generation Agent",
];

/** `attemptNumber`/`attemptCount` cover agents the 12-agent Master
 * Orchestrator pipeline can legitimately re-run in place - e.g. Recommendation
 * Agent retries when its own confidence_score comes back below threshold
 * (see _route_after_recommendation in workflow.py). Each run gets its own
 * negotiation-log entry with the same agent_name, so without this label two
 * (or more) identically-titled cards in a row read as a rendering bug rather
 * than "the pipeline retried this step". */
function AgentExplainer({
  run,
  nameById,
  attemptNumber,
  attemptCount,
}: {
  run: AgentRunResponse;
  nameById: Map<string, string>;
  attemptNumber: number;
  attemptCount: number;
}) {
  const text = agentRawMessage(run);
  const Icon = AGENT_ICON[run.agent_name] ?? Sparkles;
  const isFallback = agentLogSource(run) === "fallback";
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <h3 className="font-medium text-foreground">{run.agent_name}</h3>
        {attemptCount > 1 && (
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
            Attempt {attemptNumber} of {attemptCount}
          </span>
        )}
        {isFallback && (
          <span
            title="No configured LLM provider responded for this stage - this is the deterministic fallback text, not a model-generated response."
            className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-300"
          >
            Fallback response
          </span>
        )}
        <span className="ml-auto rounded-full bg-muted/60 px-2.5 py-0.5 text-[11px] text-foreground/80">
          {run.status}
        </span>
      </div>
      <ExplainerBoundary fallbackText={text}>
        {run.agent_name === "Discovery Agent" && <DiscoveryExplainer rawText={text} />}
        {run.agent_name === "Dependency Agent" && <DependencyExplainer rawText={text} />}
        {run.agent_name === "Risk Agent" && <RiskExplainer rawText={text} />}
        {run.agent_name === "Planner Agent" && <PlannerExplainer rawText={text} nameById={nameById} />}
        {run.agent_name === "Recommendation Agent" && <RecommendationExplainer rawText={text} />}
        {run.agent_name === "Report Generation Agent" && <ReportGenerationExplainer rawText={text} />}
        {!KNOWN_AGENT_TYPES.includes(run.agent_name) && <RawMessage text={text} />}
      </ExplainerBoundary>
    </Card>
  );
}

/** Phases 4-7: the Discovery/Dependency/Planner/Risk LangGraph negotiation loop
 * - Discovery is grounded in whatever's been uploaded via RAG retrieval, and the
 * LLM call underneath is Bedrock-preferred. Renders each agent's structured
 * output (orphans, shared-DB risk, cycles, objections, wave rationale) instead
 * of a raw text dump - the proposal's "Explainable Recommendation Engine...
 * citing specific dependencies, risk scores" requirement.
 *
 * A run started here shares the same global background stream everything
 * else uses (PlannerRunProvider/PlannerRunPanel - see lib/planner-run-context.tsx),
 * so it survives navigating away mid-run. On mount this page also fetches the
 * last completed run from the backend (GET .../agent-runs/latest) so
 * revisiting it - including via the "View" action on the completion
 * notification after an auto-started run - shows the result immediately,
 * with no fresh run required. */
export function PlannerPage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;
  const plannerRun = usePlannerRun();
  const isLiveHere = plannerRun.assessmentId === assessmentId && plannerRun.status !== "idle";

  const [persistedResult, setPersistedResult] = useState<RunPlannerResponse | null>(null);
  const [loadingPersisted, setLoadingPersisted] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graph, setGraph] = useState<AssessmentGraphResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingPersisted(true);
    v1Api
      .getLatestPlannerResult(assessmentId)
      .then((data) => {
        if (!cancelled) setPersistedResult(data);
      })
      .catch(() => {
        if (!cancelled) setPersistedResult(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingPersisted(false);
      });
    return () => {
      cancelled = true;
    };
  }, [assessmentId]);

  // Waves/agent output only carry component ids - fetch the graph once so
  // those ids can be rendered as the actual service names everywhere below,
  // instead of raw slugs like "order_service".
  useEffect(() => {
    let cancelled = false;
    v1Api
      .getAssessmentGraph(assessmentId)
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch(() => {
        if (!cancelled) setGraph(null);
      });
    return () => {
      cancelled = true;
    };
  }, [assessmentId]);

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of graph?.nodes ?? []) map.set(n.id, n.name);
    return map;
  }, [graph]);

  function handleRun() {
    setError(null);
    plannerRun.startRun(assessmentId);
  }

  // PlannerRunPanel (mounted globally, see App.tsx) auto-dismisses the shared
  // run context ~10s after completion, resetting it to idle - once that
  // happens isLiveHere goes false and this page falls back to
  // persistedResult, which was only fetched once on mount (before the run
  // finished). Without this, the page would show live results briefly then
  // go blank when the panel's timer fires. Refetch the moment the run
  // completes so persistedResult is already current by the time that happens.
  useEffect(() => {
    if (!isLiveHere || plannerRun.status !== "complete") return;
    let cancelled = false;
    v1Api
      .getLatestPlannerResult(assessmentId)
      .then((data) => {
        if (!cancelled) setPersistedResult(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isLiveHere, plannerRun.status, assessmentId]);

  const busy = isLiveHere && plannerRun.status === "running";
  const result = isLiveHere ? plannerRun.result : persistedResult;
  const agentRuns = isLiveHere ? plannerRun.events : (persistedResult?.agent_runs ?? []);
  const liveErrorMessage = isLiveHere && plannerRun.status === "error" ? plannerRun.errorMessage : null;

  // Some pipeline agents (e.g. Recommendation Agent, retried on low
  // confidence - see _route_after_recommendation in workflow.py) legitimately
  // run more than once, each getting its own negotiation-log entry with the
  // same agent_name - label these "Attempt N of M" so repeats read as an
  // intentional retry rather than a duplicate-rendering bug.
  const attemptInfo = useMemo(() => {
    const totalByName = new Map<string, number>();
    for (const run of agentRuns) totalByName.set(run.agent_name, (totalByName.get(run.agent_name) ?? 0) + 1);
    const seenByName = new Map<string, number>();
    return agentRuns.map((run) => {
      const attemptNumber = (seenByName.get(run.agent_name) ?? 0) + 1;
      seenByName.set(run.agent_name, attemptNumber);
      return { attemptNumber, attemptCount: totalByName.get(run.agent_name) ?? 1 };
    });
  }, [agentRuns]);

  return (
    <div className="space-y-6">
      <InfoBanner id="planner" title="What is Wave Planner?">
        <p>
          A pipeline of 12 AI agents - Discovery, Dependency Analysis, Enterprise Digital Twin, Migration
          Intelligence Graph, Complexity Assessment, Risk Assessment, Cloud Readiness, Migration Planner,
          Simulation, Recommendation, Explainability, and Report Generation - negotiate the safest order to
          migrate your systems, grouping them into sequential "waves" so nothing moves before what it depends
          on. Circular dependencies, shared-database risks, and high-criticality violations get flagged and
          resolved during the negotiation, not discovered after the fact - see each agent's reasoning below
          once a run finishes.
        </p>
      </InfoBanner>

      <Card className="p-6">
        <h2 className="mb-1 font-medium text-foreground">Run multi agent planner</h2>
        <div className="flex flex-wrap gap-3">
          <Button type="button" onClick={handleRun} disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? "Running agents..." : "Run planner"}
          </Button>
        </div>
        {(error || liveErrorMessage) && <p className="mt-3 text-sm text-destructive">{error ?? liveErrorMessage}</p>}
        {!isLiveHere && !loadingPersisted && !persistedResult && (
          <p className="mt-3 text-xs text-muted-foreground">
            No planner run yet for this assessment - run it here, or start it automatically by starting a new
            assessment with documents attached.
          </p>
        )}
      </Card>

      {busy && agentRuns.length === 0 && (
        <Card className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" /> Starting Discovery Agent...
        </Card>
      )}

      {result && (
        <Card className="p-6">
          <h2 className="mb-3 font-medium text-foreground">Proposed migration waves</h2>
          <ol className="list-inside list-decimal space-y-1 text-sm text-muted-foreground">
            {result.waves.map((wave, i) => (
              <li key={i}>
                <span className="text-foreground">Wave {i + 1}:</span>{" "}
                {wave.map((componentId) => nameById.get(componentId) ?? componentId).join(", ")}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {result && <PipelineMetricsSection result={result} />}

      {agentRuns.length > 0 && (
        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Explainability - agent negotiation
          </h2>
          <div className="space-y-4">
            {agentRuns.map((run, i) => (
              <AgentExplainer
                key={run.agent_run_id}
                run={run}
                nameById={nameById}
                attemptNumber={attemptInfo[i].attemptNumber}
                attemptCount={attemptInfo[i].attemptCount}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
