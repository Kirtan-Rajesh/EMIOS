import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ShieldAlert, Sparkles, TrendingUp, Wallet } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/Card";
import { InfoBanner } from "@/components/InfoBanner";
import { KpiCard } from "@/components/KpiCard";
import { SimulationScenariosCard } from "@/components/pipeline-metrics";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { layoutWithDagre } from "@/lib/graph-layout";
import { useTheme } from "@/lib/theme-context";
import { ApiError, v1Api } from "@/lib/api";
import type { DependencyEdge, RunPlannerResponse, ServiceNode, SimulationResultResponse } from "@/types/api";

const RISK_HIGH = "#f43f5e";
const RISK_MEDIUM = "#f59e0b";
const RISK_LOW = "#10b981";

function riskColor(p: number): string {
  if (p >= 0.6) return RISK_HIGH;
  if (p >= 0.25) return RISK_MEDIUM;
  return RISK_LOW;
}

function layoutRiskNodes(services: ServiceNode[], edges: Pick<Edge, "source" | "target">[]): Node[] {
  const rawNodes: Node[] = services.map((s) => ({
    id: s.id,
    position: { x: 0, y: 0 },
    data: { label: `${s.name}\n${Math.round(s.failure_probability * 100)}% risk` },
    style: {
      background: riskColor(s.failure_probability),
      color: "#0b0f14",
      borderRadius: 8,
      border: "1px solid rgba(255,255,255,0.15)",
      fontSize: 11,
      fontWeight: 600,
      padding: 6,
      whiteSpace: "pre-line",
      textAlign: "center",
    },
  }));
  return layoutWithDagre(rawNodes, edges, "LR");
}

/** critical_paths only records the specific hops whose propagated risk cleared
 * the engine's cutoff (see run_cascading_failure) - a node whose risk decays
 * just under that threshold is still a real dependent, it just isn't on any
 * recorded path. Building edges purely from critical_paths therefore drops
 * real topology edges whenever risk decays past that node, rendering it as a
 * disconnected floating box even though it's genuinely connected. Drawing
 * from the assessment's real dependency edges instead - the same ones the
 * Digital Twin graph renders - keeps every real connection visible, using
 * critical_paths only to decide which edges get the "active cascade" styling. */
function buildRiskEdges(
  edges: Pick<DependencyEdge, "source" | "target">[],
  criticalPaths: string[][],
): Edge[] {
  const onCriticalPath = new Set<string>();
  for (const path of criticalPaths) {
    for (let i = 0; i < path.length - 1; i++) {
      onCriticalPath.add(`${path[i]}->${path[i + 1]}`);
    }
  }

  const seen = new Set<string>();
  const result: Edge[] = [];
  for (const e of edges) {
    // A dependency edge is "source depends on target" - propagation flows the
    // opposite way (a failing target drags its dependent source down with
    // it), matching the direction critical_paths itself uses.
    const key = `${e.target}->${e.source}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const critical = onCriticalPath.has(key);
    result.push({
      id: key,
      source: e.target,
      target: e.source,
      animated: critical,
      style: { stroke: critical ? RISK_HIGH : "#475569" },
    });
  }
  return result;
}

/** Maps internal node ids to human-readable names, using the simulation's own
 * impacted-services list (always in sync with critical_paths ids) as the
 * primary source and the assessment's saved graph as a fallback - mirrors the
 * `nameById` pattern already used by GraphPage's ConnectionList. */
function buildNameById(impactedServices: ServiceNode[], graphNodes: ServiceNode[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const node of graphNodes) map.set(node.id, node.name);
  for (const node of impactedServices) map.set(node.id, node.name);
  return map;
}

function buildRiskById(impactedServices: ServiceNode[]): Map<string, number> {
  return new Map(impactedServices.map((s) => [s.id, s.failure_probability]));
}

function formatPath(path: string[], nameById: Map<string, string>): string {
  return path.map((id) => nameById.get(id) ?? id).join(" → ");
}

/** Picks the critical path whose endpoint carries the highest propagated
 * failure risk (ties broken by the longer/deeper chain) - used both to sort
 * the critical-paths list and to call out the single worst path in the
 * plain-English summary. */
function pickMostSeverePath(paths: string[][], riskById: Map<string, number>): string[] | null {
  if (paths.length === 0) return null;
  let best = paths[0];
  let bestScore = -1;
  for (const path of paths) {
    const endRisk = riskById.get(path[path.length - 1]) ?? 0;
    const score = endRisk * 1000 + path.length;
    if (score > bestScore) {
      bestScore = score;
      best = path;
    }
  }
  return best;
}

/** Phase: What-If Simulation - cascading-failure + Monte Carlo forecast against
 * the assessment's saved topology. Renders the full Monte Carlo confidence-
 * interval/distribution data the backend already computes (previously
 * discarded by the UI), and visually propagates risk onto a mini topology
 * view - the proposal's "visually calculate and propagate downstream failure
 * risks across the architecture grid" success criterion. */
export function SimulatePage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;
  const { theme } = useTheme();
  const [targetId, setTargetId] = useState("");
  const [graphNodes, setGraphNodes] = useState<ServiceNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<DependencyEdge[]>([]);
  const [simulation, setSimulation] = useState<SimulationResultResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pipelineResult, setPipelineResult] = useState<RunPlannerResponse | null>(null);

  const loadGraphNodes = useCallback(async () => {
    try {
      const result = await v1Api.getAssessmentGraph(assessmentId);
      setGraphNodes(result.nodes);
      setGraphEdges(result.edges);
      setTargetId((current) => current || result.nodes[0]?.id || "");
    } catch {
      setGraphNodes([]);
      setGraphEdges([]);
    }
  }, [assessmentId]);

  useEffect(() => {
    loadGraphNodes();
  }, [loadGraphNodes]);

  // Show whatever simulation already completed for this assessment (e.g. run
  // last session, or on a different tab) rather than starting blank every
  // time this page is visited - matches the "landing page shows the latest
  // completed result" pattern used elsewhere (Overview, Planner).
  useEffect(() => {
    v1Api
      .getSimulation(assessmentId)
      .then(setSimulation)
      .catch(() => undefined);
  }, [assessmentId]);

  // Simulation scenarios here are the 12-agent Wave Planner pipeline's
  // per-strategy (rehost/replatform/refactor) cost-benefit comparison -
  // distinct from this page's own single-service cascading-failure
  // simulation above. Moved here (from Wave Planner's Pipeline metrics)
  // since strategy simulation belongs alongside this page's other what-if
  // tooling; still just a read of the last completed planner run, not
  // re-triggered from here.
  useEffect(() => {
    v1Api
      .getLatestPlannerResult(assessmentId)
      .then(setPipelineResult)
      .catch(() => setPipelineResult(null));
  }, [assessmentId]);

  const riskEdges = useMemo(
    () => (simulation ? buildRiskEdges(graphEdges, simulation.critical_paths) : []),
    [simulation, graphEdges],
  );
  const riskNodes = useMemo(
    () => (simulation ? layoutRiskNodes(simulation.impacted_services, riskEdges) : []),
    [simulation, riskEdges],
  );
  const nameById = useMemo(
    () => buildNameById(simulation?.impacted_services ?? [], graphNodes),
    [simulation, graphNodes],
  );
  const riskById = useMemo(() => buildRiskById(simulation?.impacted_services ?? []), [simulation]);
  const mostSeverePath = useMemo(
    () => (simulation ? pickMostSeverePath(simulation.critical_paths, riskById) : null),
    [simulation, riskById],
  );

  async function handleSimulate() {
    setError(null);
    setBusy(true);
    try {
      const result = await v1Api.runSimulation(assessmentId, { target_id: targetId });
      setSimulation(result);
      toast.success("Simulation complete.");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Simulation failed - save a topology in the Digital Twin Graph tab first.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <InfoBanner id="simulate" title="What is What-If Simulation?">
        <p>
          Pick any service and simulate what happens if it fails or goes offline mid-migration. The engine
          traces cascading risk to everything that depends on it, then runs a Monte Carlo forecast - thousands
          of simulated outcomes - to give you a realistic <strong className="text-foreground/80">range</strong>{" "}
          for migration cost and duration, rather than a single unreliable guess.
        </p>
      </InfoBanner>

      {pipelineResult?.simulation_results && (
        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Strategy simulation - Wave Planner pipeline
          </h2>
          <SimulationScenariosCard simulationResults={pipelineResult.simulation_results} />
        </div>
      )}

      <Card className="p-6">
        <h2 className="mb-3 font-medium text-foreground">Simulate a migration</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-sm text-foreground/80" htmlFor="target">
              Target service
            </label>
            {graphNodes.length > 0 ? (
              <Select value={targetId} onValueChange={setTargetId}>
                <SelectTrigger id="target" className="min-w-[220px]">
                  <SelectValue placeholder="Select a service" />
                </SelectTrigger>
                <SelectContent>
                  {graphNodes.map((node) => (
                    <SelectItem key={node.id} value={node.id}>
                      {node.name} ({node.id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <input
                id="target"
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                placeholder="Save a topology in Digital Twin Graph first"
                className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
              />
            )}
          </div>
          <Button type="button" onClick={handleSimulate} disabled={busy || !targetId}>
            {busy ? "Simulating..." : "Simulate migration risk"}
          </Button>
        </div>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </Card>

      {simulation && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <KpiCard
              icon={Wallet}
              label="Current hosting cost"
              value={`$${Math.round(simulation.total_hosting_cost).toLocaleString()}`}
              sub="of the simulated topology, annualized"
              tone="destructive"
            />
            <KpiCard
              icon={TrendingUp}
              label="Potential savings"
              value={`$${Math.round(simulation.potential_savings).toLocaleString()}`}
              sub="projected if this migration proceeds"
              tone="success"
            />
            <KpiCard
              icon={ShieldAlert}
              label="Revenue at risk"
              value={`$${Math.round(simulation.revenue_at_risk).toLocaleString()}/mo`}
              sub="if the target service fails mid-migration"
              tone="destructive"
            />
          </div>

          <Card className="border-primary/30 bg-primary/[0.04] p-6">
            <p className="text-sm leading-relaxed text-foreground/90">
              Migrating <strong className="text-foreground">{nameById.get(simulation.target_id) ?? simulation.target_id}</strong>{" "}
              would put{" "}
              <strong className="text-foreground">
                {(() => {
                  const count = simulation.impacted_services.filter(
                    (s) => s.id !== simulation.target_id && s.failure_probability > 0.05,
                  ).length;
                  return `${count} other service${count === 1 ? "" : "s"}`;
                })()}
              </strong>{" "}
              at risk.
              {mostSeverePath && mostSeverePath.length > 1 && (
                <>
                  {" "}
                  The most severe cascading impact runs through{" "}
                  <strong className="text-foreground">{formatPath(mostSeverePath, nameById)}</strong>, ending at{" "}
                  {Math.round((riskById.get(mostSeverePath[mostSeverePath.length - 1]) ?? 0) * 100)}% failure risk.
                </>
              )}{" "}
              Expect roughly{" "}
              <strong className="text-foreground">
                {Math.round(simulation.monte_carlo.confidence_90_duration[0])}–
                {Math.round(simulation.monte_carlo.confidence_90_duration[1])} days
              </strong>{" "}
              and{" "}
              <strong className="text-foreground">
                ${Math.round(simulation.monte_carlo.confidence_90_cost[0]).toLocaleString()}–$
                {Math.round(simulation.monte_carlo.confidence_90_cost[1]).toLocaleString()}
              </strong>{" "}
              to complete this migration, with 90% confidence.
            </p>
          </Card>

          <Card className="p-6">
            <div className="mb-5">
              <h2 className="font-medium text-foreground">Monte Carlo forecast</h2>
              <p className="text-xs text-muted-foreground">
                {simulation.monte_carlo.distribution.length > 0
                  ? "Based on thousands of simulated outcomes, here's the realistic range for this migration."
                  : "No distribution data returned."}
              </p>
            </div>

            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              <RangeSummary
                label="Duration"
                unit="days"
                low={simulation.monte_carlo.confidence_90_duration[0]}
                expected={simulation.monte_carlo.expected_duration}
                high={simulation.monte_carlo.confidence_90_duration[1]}
                color="#3B82F6"
                format={(v) => `${Math.round(v)}`}
              />
              <RangeSummary
                label="Cost"
                unit=""
                low={simulation.monte_carlo.confidence_90_cost[0]}
                expected={simulation.monte_carlo.expected_cost}
                high={simulation.monte_carlo.confidence_90_cost[1]}
                color="#8B5CF6"
                format={(v) => `$${Math.round(v).toLocaleString()}`}
              />
            </div>

            <p className="mt-5 border-t border-border pt-4 text-xs text-muted-foreground">
              90% of simulated runs land inside the shaded range - the marker shows the single most likely
              (expected) outcome.
            </p>
          </Card>

          <Card className="p-6">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <h2 className="font-medium text-foreground">Risk propagation</h2>
                <p className="text-xs text-muted-foreground">
                  Failure risk cascading outward from '{nameById.get(simulation.target_id) ?? simulation.target_id}'
                  across dependent services
                </p>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <LegendDot color={RISK_LOW} label="Low" />
                <LegendDot color={RISK_MEDIUM} label="Medium" />
                <LegendDot color={RISK_HIGH} label="High" />
                <LegendDot color="#475569" label="Not on cascade path" />
              </div>
            </div>
            <div className="h-[420px] overflow-hidden rounded-lg border border-border">
              {riskNodes.length > 0 ? (
                <ReactFlow
                  nodes={riskNodes}
                  edges={riskEdges}
                  fitView
                  fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
                  minZoom={0.15}
                  colorMode={theme}
                >
                  <Background />
                  <Controls />
                </ReactFlow>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  No impacted services to visualize.
                </div>
              )}
            </div>
          </Card>

        </>
      )}

      {!simulation && (
        <Card className="p-10 text-center">
          <Sparkles className="mx-auto mb-3 h-6 w-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Run a simulation above to see the Monte Carlo forecast and risk propagation view.
          </p>
        </Card>
      )}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

/** Plain-English stand-in for the raw percentile distribution charts this
 * replaced - a best-case/expected/worst-case range bar reads at a glance,
 * where a percentile curve needs the viewer to already understand what a
 * percentile is. */
function RangeSummary({
  label,
  unit,
  low,
  expected,
  high,
  color,
  format,
}: {
  label: string;
  unit: string;
  low: number;
  expected: number;
  high: number;
  color: string;
  format: (v: number) => string;
}) {
  const span = Math.max(high - low, 1);
  const markerPct = Math.min(100, Math.max(0, ((expected - low) / span) * 100));
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold text-foreground">
          {format(expected)} {unit}
        </p>
      </div>
      <div className="relative mt-4 h-2 rounded-full bg-muted/40">
        <div className="absolute inset-y-0 left-0 w-full rounded-full" style={{ background: `${color}33` }} />
        <div
          className="absolute -top-1.5 h-5 w-1 -translate-x-1/2 rounded-full border-2 border-background"
          style={{ left: `${markerPct}%`, background: color }}
          title={`Expected: ${format(expected)} ${unit}`}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Best case: {format(low)} {unit}
        </span>
        <span>
          Worst case: {format(high)} {unit}
        </span>
      </div>
    </div>
  );
}
