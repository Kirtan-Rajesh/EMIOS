import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  Database,
  FileText,
  Gauge,
  Layers,
  Loader2,
  Puzzle,
  Server,
  ShieldAlert,
  Sparkles,
  Wallet,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "@/components/Card";
import { InfoBanner } from "@/components/InfoBanner";
import { KpiCard } from "@/components/KpiCard";
import { CloudReadinessCard, ComplexityCard, EnterpriseRiskCard } from "@/components/pipeline-metrics";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { v1Api } from "@/lib/api";
import { useDiscoveryRun } from "@/lib/discovery-run-context";
import { usePlannerRun } from "@/lib/planner-run-context";
import { useRefetchOnRunComplete } from "@/lib/use-refetch-on-run-complete";
import { useReportRun } from "@/lib/report-run-context";
import { useTheme } from "@/lib/theme-context";
import { cn } from "@/lib/utils";
import type {
  Assessment,
  AssessmentGraphResponse,
  AssessmentUpload,
  MigrationWave,
  ReportResponse,
  RunPlannerResponse,
} from "@/types/api";

// Risk/chart colors used across this page are consumed as raw style/SVG
// values (Recharts Cell fill, gradient stops, tooltip style objects) rather
// than className, so they can't pick up the theme via a `dark:` Tailwind
// variant - each is picked explicitly per theme instead, see useThemeColors().
const RISK_COLORS_LIGHT: Record<string, string> = { Low: "#2563eb", Medium: "#f59e0b", High: "#ef4444" };
const RISK_COLORS_DARK: Record<string, string> = { Low: "#30E3CA", Medium: "#FFB020", High: "#DA0037" };

function useThemeColors() {
  const { theme } = useTheme();
  const dark = theme === "dark";
  return {
    theme,
    riskColors: dark ? RISK_COLORS_DARK : RISK_COLORS_LIGHT,
    ringFrom: dark ? "#30E3CA" : "#2563eb",
    ringTo: dark ? "#FF204E" : "#ef4444",
    tooltipStyle: dark
      ? { background: "#0f172acc", border: "1px solid #ffffff1a", borderRadius: 8, fontSize: 12 }
      : { background: "#ffffffe6", border: "1px solid #0000001a", borderRadius: 8, fontSize: 12 },
    axisTick: dark ? "#94A3B8" : "#64748b",
    gridStroke: dark ? "#ffffff10" : "#00000010",
    cursorFill: dark ? "#ffffff08" : "#00000008",
    barFill: dark ? "#30E3CA" : "#2563eb",
  };
}

function ScoreRing({ value, loading }: { value: number; loading?: boolean }) {
  const { ringFrom, ringTo } = useThemeColors();
  const r = 34;
  const c = 2 * Math.PI * r;
  const offset = c - (Math.max(0, Math.min(100, value)) / 100) * c;
  return (
    <div className="relative h-[72px] w-[72px] shrink-0">
      <svg viewBox="0 0 80 80" className={cn("h-[72px] w-[72px] -rotate-90", loading && "animate-spin-slow")}>
        <circle cx="40" cy="40" r={r} strokeWidth="8" className="fill-none stroke-foreground/10" />
        <circle
          cx="40"
          cy="40"
          r={r}
          strokeWidth="8"
          strokeLinecap="round"
          className="fill-none"
          stroke="url(#ringGrad)"
          strokeDasharray={loading ? `${c * 0.25} ${c}` : c}
          strokeDashoffset={loading ? 0 : offset}
        />
        <defs>
          <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={ringFrom} />
            <stop offset="100%" stopColor={ringTo} />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        ) : (
          <span className="text-xl font-semibold text-foreground">{Math.round(value)}</span>
        )}
        <span className="text-[9px] uppercase tracking-wider text-muted-foreground">
          {loading ? "Generating" : "Ready"}
        </span>
      </div>
    </div>
  );
}

function EmptyChartState({ text, to, cta }: { text: string; to: string; cta: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <p className="text-xs text-muted-foreground">{text}</p>
      <Link to={to} className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80">
        {cta} <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}

/** Per-assessment landing page: hero + KPIs + charts + inventory + AI
 * recommendations, all wired to real data (never mock) - shows an empty-state
 * CTA into the relevant tab wherever a step hasn't been run yet. */
export function OverviewPage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;
  const location = useLocation();
  const navigate = useNavigate();
  const plannerRun = usePlannerRun();
  const { startRun } = plannerRun;
  const discoveryRun = useDiscoveryRun();
  const reportRun = useReportRun();
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  // Overall-system metrics from the latest completed planner run (Enterprise
  // Risk / Complexity / Risk Agents) - deliberately NOT the What-If Simulation
  // result. That's a separate scenario-testing tool ("what happens if THIS
  // one service fails mid-migration") and showing its numbers here made the
  // Overview page look like it was describing the whole system when it was
  // actually describing whichever one target the user last simulated. See
  // SimulatePage for those scenario-specific numbers instead.
  const [plannerResult, setPlannerResult] = useState<RunPlannerResponse | null>(null);
  const [graph, setGraph] = useState<AssessmentGraphResponse | null>(null);
  const [waves, setWaves] = useState<MigrationWave[]>([]);
  const [uploads, setUploads] = useState<AssessmentUpload[]>([]);

  // This page's component instance is reused across different assessments
  // (React Router doesn't remount it on a :id param change alone) - without
  // this guard, navigating from assessment A to B while A's slower requests
  // are still in flight let A's response land after B's and overwrite B's
  // page with A's customer name/cost/readiness/risk data. `current` is kept
  // up to date every render (not inside an effect) so it reflects the latest
  // assessmentId immediately, before any of refresh()'s promises resolve.
  const assessmentIdRef = useRef(assessmentId);
  assessmentIdRef.current = assessmentId;

  const { riskColors, tooltipStyle, axisTick, gridStroke, cursorFill, barFill } = useThemeColors();

  function refresh() {
    const forId = assessmentId;
    const guard = <T,>(setter: (value: T) => void) => (value: T) => {
      if (assessmentIdRef.current === forId) setter(value);
    };
    v1Api.getAssessment(forId).then(guard(setAssessment)).catch(() => undefined);
    v1Api.getReport(forId).then(guard(setReport)).catch(() => undefined);
    v1Api.getLatestPlannerResult(forId).then(guard(setPlannerResult)).catch(() => undefined);
    v1Api.getAssessmentGraph(forId).then(guard(setGraph)).catch(() => undefined);
    v1Api.listWaves(forId).then(guard(setWaves)).catch(() => undefined);
    v1Api.listUploads(forId).then(guard(setUploads)).catch(() => undefined);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessmentId]);

  // A Document Discovery run (started from Documents or New Assessment) can
  // finish while the user is sitting on this page, or land here having
  // finished elsewhere - either way, re-fetch once so the graph-derived KPIs
  // and inventory table aren't stuck showing pre-discovery state. Driven by
  // DiscoveryRunProvider (app root, survives navigation) rather than anything
  // local to this page.
  useRefetchOnRunComplete(discoveryRun.status, discoveryRun.assessmentId, assessmentId, refresh);

  // A planner run (auto-started below, or manually from PlannerPage) persists
  // its migration waves in the background (see planner-run-context.tsx) - if
  // it finishes while the user is still sitting on this page (the common case
  // right after "Start assessment"), re-fetch once so the wave plan chart
  // doesn't stay stuck showing the pre-planner empty state. Same one-shot
  // pattern as the discoveryRun effect above, driven by PlannerRunProvider
  // (app root, survives navigation) rather than anything local to this page.
  useEffect(() => {
    if (plannerRun.assessmentId === assessmentId && plannerRun.status === "complete") {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessmentId, plannerRun.status, plannerRun.assessmentId]);

  // Report generation itself now auto-starts once the planner run above
  // finishes (see report-run-context.tsx, chained from PlannerRunProvider) -
  // re-fetch once THAT completes too, so readiness/recommendations don't
  // stay stuck on stale (or empty) data between "planner done" and "report
  // done". Same one-shot pattern as the two effects above.
  useEffect(() => {
    if (reportRun.assessmentId === assessmentId && reportRun.status === "complete") {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessmentId, reportRun.status, reportRun.assessmentId]);


  // Landed here right after "Start assessment" finished building the graph
  // (see NewAssessmentPage.handleStart) - auto-start the planner agents in
  // the background (PlannerRunPanel shows their live reasoning on the side).
  // The state flag is stripped immediately so a later reload/back-navigation
  // to this same URL doesn't re-trigger a run.
  useEffect(() => {
    const state = location.state as { autoStartPlanner?: boolean } | null;
    if (state?.autoStartPlanner) {
      startRun(assessmentId);
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assessmentId, location.state]);

  const nodeNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of graph?.nodes ?? []) map.set(n.id, n.name);
    return map;
  }, [graph]);

  // Baseline risk per service, from each node's own failure_probability on
  // the persisted graph - same Low/Medium/High cutoffs GraphPage's riskTier()
  // uses, for visual consistency. NOT sourced from plannerResult.risk_assessment
  // (used here previously): that field is populated only by the older 4-agent
  // negotiation loop's per-service Risk Agent - the actual pipeline backing
  // the live Wave Planner today (app.agents.workflow.run_full_assessment_stream,
  // the Master Orchestrator) uses a different, portfolio-level Risk Assessment
  // Agent instead and its own docstring says outright that risk_assessment
  // "stays at its initial {}" in that pipeline's output. Reading it here meant
  // this chart silently stayed empty ("No planner run yet") forever, even
  // after a real, successful planner run - graph.nodes[].failure_probability
  // is both correct and available as soon as a graph exists, no planner run
  // required at all.
  const riskBuckets = useMemo(() => {
    const nodes = graph?.nodes ?? [];
    if (nodes.length === 0) return [];
    const buckets: Record<string, string[]> = { Low: [], Medium: [], High: [] };
    for (const node of nodes) {
      const p = Number(node.failure_probability ?? 0);
      if (p >= 0.6) buckets.High.push(node.name);
      else if (p >= 0.25) buckets.Medium.push(node.name);
      else buckets.Low.push(node.name);
    }
    return Object.entries(buckets)
      .map(([name, services]) => ({ name, value: services.length, services, color: riskColors[name] }))
      .filter((b) => b.value > 0);
  }, [graph, riskColors]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function RiskTooltip({ active, payload }: any) {
    if (!active || !payload?.length) return null;
    const bucket = payload[0].payload as { name: string; value: number; services: string[] };
    return (
      <div style={tooltipStyle} className="max-w-[220px] p-2.5">
        <p className="text-xs font-semibold text-foreground">
          {bucket.name} risk · {bucket.value} service{bucket.value === 1 ? "" : "s"}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{bucket.services.join(", ")}</p>
      </div>
    );
  }

  const waveChartData = useMemo(
    () =>
      [...waves]
        .sort((a, b) => a.wave_number - b.wave_number)
        .map((w) => {
          const names = w.components.map((id) => nodeNameById.get(id) ?? id);
          return {
            wave: `Wave ${w.wave_number}`,
            fullLabel: `Wave ${w.wave_number}: ${names.join(", ") || "no components"}`,
            components: w.components.length,
          };
        }),
    [waves, nodeNameById],
  );

  // Drives the loading state on every card below whose numbers come from the
  // Wave Planner (readiness/risk/complexity KPIs, the complexity/enterprise-
  // risk/cloud-readiness cards, the wave chart) - without this, those cards
  // showed the same "—"/"run the planner" empty state whether the planner had
  // never been run OR was actively running right now, several minutes into a
  // real run the user had just started.
  const plannerIsRunning = plannerRun.assessmentId === assessmentId && plannerRun.status === "running";
  // Same idea, for the cards that specifically come from the Report (readiness
  // score, AI recommendations) rather than the raw planner output - these two
  // finish at different times now that report generation is its own
  // auto-started background step following the planner (see report-run-context.tsx).
  const reportIsRunning = reportRun.assessmentId === assessmentId && reportRun.status === "running";

  const nodeCount = graph?.nodes.length ?? 0;
  const dbCount = graph?.nodes.filter((n) => n.type === "Database").length ?? 0;
  // Real current hosting spend across every discovered system - not a
  // simulated scenario's projected cost.
  const totalAnnualCost = graph?.nodes.reduce((sum, n) => sum + (n.annual_cost ?? 0), 0) ?? 0;

  return (
    <div className="space-y-6">
      <InfoBanner id="overview" title="What am I looking at?">
        <p>
          This is the assessment's command center - an overall snapshot of the whole system, pulled from the
          Digital Twin Graph, the multi-agent Planner, and the Report as you complete each one. Nothing here is
          entered manually; work through the tabs on the left in order (Documents → Digital Twin Graph → Wave
          Planner → Report) and this page fills in automatically.{" "}
          <Link to="simulate" className="text-primary hover:underline">
            What-If Simulation
          </Link>{" "}
          is a separate tool for testing one specific migration scenario at a time - its results live on that
          tab, not here, so this overview always reflects the system as a whole rather than whichever scenario
          was last tested.
        </p>
      </InfoBanner>

      <Card className="overflow-hidden">
        <div className="relative p-4 sm:p-5">
          <div className="absolute inset-0 bg-gradient-to-r from-primary/10 via-transparent to-destructive/10" />
          <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-4">
              <ScoreRing value={report?.readiness_score ?? 0} loading={reportIsRunning && !report} />
              <div>
                <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
                  {assessment?.status ?? "loading"}
                </span>
                <h2 className="mt-1 text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
                  {assessment?.customer_name}
                </h2>
                <p className="mt-0.5 max-w-lg text-sm text-muted-foreground">
                  {assessment?.project_name} - migrating to {assessment?.target_cloud}.
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-1.5 text-xs">
                  <span className="flex items-center gap-1.5 text-foreground/80">
                    <Server className="h-3.5 w-3.5 text-primary" /> {nodeCount} services
                  </span>
                  <span className="flex items-center gap-1.5 text-foreground/80">
                    <Database className="h-3.5 w-3.5 text-destructive dark:text-[#FF204E]" /> {dbCount} databases
                  </span>
                  <span className="flex items-center gap-1.5 text-foreground/80">
                    <Layers className="h-3.5 w-3.5 text-teal-400" /> {waves.length} waves planned
                  </span>
                  <Link
                    to="documents"
                    className="flex items-center gap-1.5 text-foreground/80 transition hover:text-foreground"
                  >
                    <FileText className="h-3.5 w-3.5 text-amber-400" /> {uploads.length} document
                    {uploads.length === 1 ? "" : "s"}
                  </Link>
                </div>
              </div>
            </div>
            <Link
              to="report"
              className="flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E] dark:shadow-lg dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
            >
              <Sparkles className="h-4 w-4" /> View report
            </Link>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          icon={Gauge}
          label="Migration readiness"
          value={report ? `${Math.round(report.readiness_score)}%` : "—"}
          sub={report ? "from latest report" : "generate a report"}
          tone="primary"
          loading={reportIsRunning && !report}
        />
        <KpiCard
          icon={Wallet}
          label="Total annual hosting cost"
          value={nodeCount > 0 ? `$${Math.round(totalAnnualCost).toLocaleString()}` : "—"}
          sub={nodeCount > 0 ? `across ${nodeCount} services` : "add a topology"}
          tone="destructive"
        />
        <KpiCard
          icon={ShieldAlert}
          label="Overall risk score"
          value={
            plannerResult?.enterprise_risk ? `${Math.round(plannerResult.enterprise_risk.risk_score * 100)}%` : "—"
          }
          sub={plannerResult?.enterprise_risk ? "from latest planner run" : "run the planner"}
          tone="destructive"
          loading={plannerIsRunning && !plannerResult?.enterprise_risk}
        />
        <KpiCard
          icon={Puzzle}
          label="Migration complexity"
          value={plannerResult?.complexity ? `${Math.round(plannerResult.complexity.complexity_score * 100)}%` : "—"}
          sub={plannerResult?.complexity ? "from latest planner run" : "run the planner"}
          tone="warning"
          loading={plannerIsRunning && !plannerResult?.complexity}
        />
      </div>

      {plannerIsRunning && !plannerResult?.complexity && !plannerResult?.enterprise_risk && !plannerResult?.cloud_readiness ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {["Complexity", "Enterprise risk", "Cloud readiness"].map((label) => (
            <Card key={label} className="flex flex-col items-center justify-center gap-2 p-6 text-center">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <p className="text-xs text-muted-foreground">{label} - planner running...</p>
            </Card>
          ))}
        </div>
      ) : (
        (plannerResult?.complexity || plannerResult?.enterprise_risk || plannerResult?.cloud_readiness) && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {plannerResult.complexity && <ComplexityCard complexity={plannerResult.complexity} />}
            {plannerResult.enterprise_risk && <EnterpriseRiskCard enterpriseRisk={plannerResult.enterprise_risk} />}
            {plannerResult.cloud_readiness && <CloudReadinessCard cloudReadiness={plannerResult.cloud_readiness} />}
          </div>
        )
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-4 lg:col-span-2">
          <h3 className="text-sm font-semibold text-foreground">Migration wave planner</h3>
          <p className="text-xs text-muted-foreground">Components per wave</p>
          <div className="mt-3 h-32">
            {waveChartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={waveChartData} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
                  <XAxis
                    dataKey="wave"
                    tick={{ fill: axisTick, fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                  />
                  <YAxis
                    tick={{ fill: axisTick, fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    cursor={{ fill: cursorFill }}
                    labelFormatter={(_, payload) => payload?.[0]?.payload?.fullLabel ?? ""}
                  />
                  <Bar dataKey="components" fill={barFill} radius={[6, 6, 0, 0]} maxBarSize={54} />
                </BarChart>
              </ResponsiveContainer>
            ) : plannerIsRunning ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                <Loader2 className="h-5 w-5 animate-spin text-primary" />
                <p className="text-xs text-muted-foreground">Wave Planner is running - waves will appear here when it finishes.</p>
              </div>
            ) : (
              <EmptyChartState text="No waves saved yet." to="planner" cta="Run the planner" />
            )}
          </div>
          {waves.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-border pt-3 text-xs text-foreground/80">
              {[...waves]
                .sort((a, b) => a.wave_number - b.wave_number)
                .map((w) => {
                  const names = w.components.map((id) => nodeNameById.get(id) ?? id);
                  return (
                    <li key={w.wave_number}>
                      <span className="font-medium text-foreground">Wave {w.wave_number}:</span>{" "}
                      {names.join(", ") || "no components"}
                    </li>
                  );
                })}
            </ul>
          )}
        </Card>

        <Card className="p-4">
          <h3 className="text-sm font-semibold text-foreground">Risk distribution</h3>
          <p className="text-xs text-muted-foreground">All services by baseline risk band</p>
          <div className="mt-2 h-64">
            {riskBuckets.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={riskBuckets}
                    dataKey="value"
                    innerRadius={56}
                    outerRadius={92}
                    paddingAngle={4}
                    stroke="none"
                  >
                    {riskBuckets.map((d, i) => (
                      <Cell key={i} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip content={RiskTooltip} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              // Sourced from the graph's own nodes (failure_probability), not the
              // planner - available as soon as a topology exists, so this is a
              // "go build a topology" empty state, not a "go run the planner" one.
              <EmptyChartState text="No topology saved yet." to="graph" cta="Go to Digital Twin Graph" />
            )}
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="overflow-hidden xl:col-span-2">
          <div className="flex items-center justify-between border-b border-border p-5">
            <div>
              <h3 className="text-sm font-semibold text-foreground">Service inventory</h3>
              <p className="text-xs text-muted-foreground">{nodeCount} services in the saved topology</p>
            </div>
            <Link to="graph" className="flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80">
              Edit topology <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="max-h-[420px] overflow-y-auto overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="text-xs uppercase tracking-wide text-muted-foreground">
                  <TableHead className="px-5">Service</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Business value</TableHead>
                  <TableHead className="px-5 text-right">Annual cost</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(graph?.nodes ?? []).map((n) => (
                  <TableRow key={n.id}>
                    <TableCell className="px-5 py-3.5 font-medium text-foreground">{n.name}</TableCell>
                    <TableCell className="text-foreground/80">{n.type}</TableCell>
                    <TableCell className="text-foreground/80">{n.business_value}</TableCell>
                    <TableCell className="px-5 py-3.5 text-right text-foreground/80">
                      ${n.annual_cost.toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {nodeCount === 0 && (
              <div className="px-5 py-10 text-center text-sm text-muted-foreground">
                No topology saved yet -{" "}
                <Link to="graph" className="text-primary hover:underline">
                  add one
                </Link>
                .
              </div>
            )}
          </div>
        </Card>

        <Card className="flex flex-col p-5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary dark:bg-gradient-to-br dark:from-[#FF204E] dark:to-[#30E3CA]">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-foreground">AI recommendations</h3>
              <p className="text-xs text-muted-foreground">From the latest report</p>
            </div>
          </div>
          <div className="mt-4 max-h-[420px] space-y-3 overflow-y-auto pr-1">
            {reportIsRunning && !report ? (
              <div className="space-y-2.5">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" /> Report is generating - recommendations will
                  appear here shortly.
                </div>
                <Skeleton className="h-14 w-full rounded-xl" />
                <Skeleton className="h-14 w-full rounded-xl" />
              </div>
            ) : report?.recommendations?.length ? (
              report.recommendations.map((rec, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-primary/20 bg-primary/5 p-3.5 text-xs leading-relaxed text-foreground/80"
                >
                  <div className="flex items-start gap-2">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                    <span>{rec}</span>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">
                No report generated yet -{" "}
                <Link to="report" className="text-primary hover:underline">
                  generate one
                </Link>{" "}
                to see recommendations.
              </p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
