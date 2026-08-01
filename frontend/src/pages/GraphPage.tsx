import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Boxes, Database, Download, ListOrdered, Server } from "lucide-react";
import { Card } from "@/components/Card";
import { InfoBanner } from "@/components/InfoBanner";
import { Button } from "@/components/ui/button";
import { ApiError, v1Api } from "@/lib/api";
import type { AssessmentGraphResponse, DependencyEdge, ServiceNode } from "@/types/api";
import { layoutWithDagre } from "@/lib/graph-layout";
import { ServiceGraphNode, type RiskTier } from "@/components/graph/ServiceGraphNode";
import { useDiscoveryRun } from "@/lib/discovery-run-context";
import { downloadTextFile } from "@/lib/download-file";
import { useTheme } from "@/lib/theme-context";
import { useRefetchOnRunComplete } from "@/lib/use-refetch-on-run-complete";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const TYPE_LEGEND: { type: string; icon: typeof Server }[] = [
  { type: "Monolith", icon: Server },
  { type: "Database", icon: Database },
  { type: "Microservice", icon: Boxes },
  { type: "Queue", icon: ListOrdered },
];

// React Flow consumes these as raw style/SVG-attribute values (edge stroke,
// MiniMap dot fill, marker color) rather than className, so they can't pick
// up the theme via a `dark:` Tailwind variant the way JSX elements do -
// picked explicitly per theme below instead (see GraphPage's `riskHex`).
const RISK_HEX_LIGHT: Record<RiskTier, string> = { low: "#2563eb", med: "#f59e0b", high: "#ef4444" };
const RISK_HEX_DARK: Record<RiskTier, string> = { low: "#30E3CA", med: "#FFB020", high: "#DA0037" };
const EDGE_IDLE_LIGHT = "#cbd5e1";
const EDGE_IDLE_DARK = "#3a3d42";
const EDGE_LABEL_LIGHT = { fill: "#475569", bg: "#ffffff" };
const EDGE_LABEL_DARK = { fill: "#9c9c95", bg: "#0d0e10" };

const nodeTypes = { service: ServiceGraphNode };

function riskTier(prob: number): RiskTier {
  return prob >= 0.6 ? "high" : prob >= 0.25 ? "med" : "low";
}

const EMPTY_NODES: ServiceNode[] = [];
const EMPTY_EDGES: DependencyEdge[] = [];

function layoutNodes(nodes: ServiceNode[], edges: DependencyEdge[]): Node[] {
  const rawNodes: Node[] = nodes.map((n) => ({
    id: n.id,
    type: "service",
    position: { x: 0, y: 0 },
    data: {
      label: n.name,
      nodeType: n.type,
      riskTier: riskTier(n.failure_probability),
      riskPct: Math.round(n.failure_probability * 100),
      dimmed: false,
      active: false,
    },
  }));
  return layoutWithDagre(rawNodes, edges, "LR");
}

/** Preserves the actual dagre position already computed for each node while
 * layering in the current hover/selection highlight state - avoids re-running
 * the layout algorithm (and therefore re-animating node positions) on every
 * mouse move. */
function withHighlight(nodes: Node[], connected: Set<string> | null, activeId: string | null): Node[] {
  if (!connected) return nodes;
  return nodes.map((n) => ({
    ...n,
    data: { ...n.data, active: n.id === activeId, dimmed: !connected.has(n.id) },
  }));
}

function layoutEdges(
  edges: DependencyEdge[],
  connected: Set<string> | null,
  litEdgeIds: Set<string> | null,
  riskHex: Record<RiskTier, string>,
  edgeIdle: string,
  edgeLabel: { fill: string; bg: string },
): Edge[] {
  return edges.map((e, i) => {
    const id = `${e.source}-${e.target}-${i}`;
    const color = e.criticality === "High" ? riskHex.high : e.criticality === "Medium" ? riskHex.med : edgeIdle;
    const lit = litEdgeIds?.has(id) ?? false;
    const dimmed = connected ? !lit : false;
    return {
      id,
      source: e.source,
      target: e.target,
      animated: e.criticality === "High" || lit,
      label: e.type,
      labelStyle: { fill: edgeLabel.fill, fontSize: 10.5, fontFamily: "var(--font-mono-ui)" },
      labelBgStyle: { fill: edgeLabel.bg, fillOpacity: 0.9 },
      labelBgPadding: [4, 2] as [number, number],
      markerEnd: { type: MarkerType.ArrowClosed, color, width: 16, height: 16 },
      style: { stroke: color, strokeWidth: lit ? 2.4 : 1.4, opacity: dimmed ? 0.15 : 1, transition: "opacity 160ms ease, stroke-width 160ms ease" },
    };
  });
}

/** Phase 3/4: the "digital twin" visualization - read-only. The graph is
 * populated exclusively by Document Discovery (Documents tab -> Process
 * Documents), which extracts systems/dependencies from uploaded documents
 * and auto-persists them here. This page only ever reads and renders
 * whatever is currently persisted (GET .../graph) - it has no way to create
 * or edit a graph directly. */
export function GraphPage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;

  const [graph, setGraph] = useState<AssessmentGraphResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<ServiceNode | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<"nodes" | "edges" | null>(null);
  // Bumped on every successful load and used as part of <ReactFlow>'s `key`
  // below - React Flow computes edge paths from each node's measured DOM
  // handle position, which is only reliably up to date on a node the very
  // first time it mounts. Updating `nodes`/`edges` props on an
  // already-mounted <ReactFlow> instance (what a plain refetch does) can
  // leave edges referencing not-yet-remeasured nodes and never draw them -
  // this was the actual cause of both "edges missing until I leave and come
  // back" (a route change remounts everything, incidentally fixing it) and
  // "Refresh doesn't work" (it updates the same mounted instance, so it
  // doesn't). Changing `key` forces a full remount on every load instead, so
  // ReactFlow always initializes fresh against the final node set.
  const [loadVersion, setLoadVersion] = useState(0);
  const discoveryRun = useDiscoveryRun();
  const { theme } = useTheme();
  const riskHex = theme === "dark" ? RISK_HEX_DARK : RISK_HEX_LIGHT;
  const edgeIdle = theme === "dark" ? EDGE_IDLE_DARK : EDGE_IDLE_LIGHT;
  const edgeLabel = theme === "dark" ? EDGE_LABEL_DARK : EDGE_LABEL_LIGHT;

  const loadGraph = useCallback(async () => {
    setLoading(true);
    try {
      const result = await v1Api.getAssessmentGraph(assessmentId);
      setGraph(result);
      setLoadVersion((v) => v + 1);
    } catch {
      setGraph(null);
    } finally {
      setLoading(false);
    }
  }, [assessmentId]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // A discovery run finishing while the user is elsewhere shouldn't require a
  // manual "Refresh" click when they get here - same one-shot pattern as
  // OverviewPage, driven by the app-root DiscoveryRunProvider rather than
  // this page's own (previously nonexistent) awareness of background runs.
  useRefetchOnRunComplete(discoveryRun.status, discoveryRun.assessmentId, assessmentId, loadGraph);

  async function handleDownloadCsv(kind: "nodes" | "edges") {
    setDownloading(kind);
    try {
      const text = await v1Api.downloadDiscoveryCsv(assessmentId, kind);
      downloadTextFile(`${kind}.csv`, text);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : `Could not download ${kind}.csv.`;
      toast.error(message);
    } finally {
      setDownloading(null);
    }
  }

  const displayNodes = graph?.nodes ?? EMPTY_NODES;
  const displayEdges = graph?.edges ?? EMPTY_EDGES;

  const baseNodes = useMemo(() => layoutNodes(displayNodes, displayEdges), [displayNodes, displayEdges]);

  const activeId = hoveredId ?? selectedNode?.id ?? null;

  const { connected, litEdgeIds } = useMemo(() => {
    if (!activeId) return { connected: null as Set<string> | null, litEdgeIds: null as Set<string> | null };
    const nodeIds = new Set<string>([activeId]);
    const edgeIds = new Set<string>();
    displayEdges.forEach((e, i) => {
      if (e.source === activeId || e.target === activeId) {
        nodeIds.add(e.source);
        nodeIds.add(e.target);
        edgeIds.add(`${e.source}-${e.target}-${i}`);
      }
    });
    return { connected: nodeIds, litEdgeIds: edgeIds };
  }, [activeId, displayEdges]);

  const nodes = useMemo(() => withHighlight(baseNodes, connected, activeId), [baseNodes, connected, activeId]);
  const edges = useMemo(
    () => layoutEdges(displayEdges, connected, litEdgeIds, riskHex, edgeIdle, edgeLabel),
    [displayEdges, connected, litEdgeIds, riskHex, edgeIdle, edgeLabel],
  );

  const upstream = useMemo(
    () => (selectedNode ? displayEdges.filter((e) => e.target === selectedNode.id) : []),
    [selectedNode, displayEdges],
  );
  const downstream = useMemo(
    () => (selectedNode ? displayEdges.filter((e) => e.source === selectedNode.id) : []),
    [selectedNode, displayEdges],
  );
  const nameById = useMemo(() => new Map(displayNodes.map((n) => [n.id, n.name])), [displayNodes]);

  function handleNodeClick(_event: React.MouseEvent, node: Node) {
    setSelectedNode((prev) => {
      const next = displayNodes.find((n) => n.id === node.id) ?? null;
      return prev?.id === next?.id ? null : next;
    });
  }

  const isEmpty = !loading && displayNodes.length === 0;

  return (
    <div className="space-y-4">
      <InfoBanner id="graph" title="What is the Digital Twin Graph?">
        <p>
          A visual map of every system, database, and service found in your uploaded documents, and how they
          depend on each other - built automatically, nothing here is drawn by hand. It's read-only, and it's
          the foundation everything else (What-If Simulation, Wave Planner, Report) reasons over, so it's worth
          re-checking after uploading more documents. Hover a node to trace its dependencies, click for full
          detail.
        </p>
      </InfoBanner>

      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Hover a node to trace its dependencies, click for full detail.
        </p>
        <div className="flex shrink-0 flex-wrap gap-2">
          {!isEmpty && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDownloadCsv("nodes")}
                disabled={downloading !== null}
              >
                <Download className="h-3.5 w-3.5" /> {downloading === "nodes" ? "..." : "nodes.csv"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleDownloadCsv("edges")}
                disabled={downloading !== null}
              >
                <Download className="h-3.5 w-3.5" /> {downloading === "edges" ? "..." : "edges.csv"}
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={loadGraph} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
      </div>

      {isEmpty ? (
        <Card className="flex flex-col items-center gap-3 p-12 text-center">
          <p className="text-sm font-medium text-foreground">No digital twin graph yet</p>
          <p className="max-w-md text-sm text-muted-foreground">
            Upload documents and run Process Documents on the Documents tab to extract systems
            and dependencies and build the graph automatically.
          </p>
          <Button asChild size="sm">
            <Link to={`/assessments/${assessmentId}/documents`}>Go to Documents</Link>
          </Button>
        </Card>
      ) : (
        <>
          <Card className="relative h-[640px] overflow-hidden dark:bg-noise">
            <ReactFlow
              key={`${assessmentId}-${loadVersion}`}
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodeClick={handleNodeClick}
              onNodeMouseEnter={(_e, node) => setHoveredId(node.id)}
              onNodeMouseLeave={() => setHoveredId(null)}
              fitView
              fitViewOptions={{ padding: 0.25, maxZoom: 1.1 }}
              minZoom={0.15}
              colorMode={theme}
              proOptions={{ hideAttribution: false }}
            >
              <Background color={theme === "dark" ? "#212226" : "#e2e8f0"} gap={26} size={1.4} />
              <Controls className="!border !border-border !bg-card/80 !shadow-none [&_button]:!border-border [&_button]:!bg-transparent [&_button]:!fill-foreground [&_button:hover]:!bg-secondary" />
              <MiniMap
                pannable
                zoomable
                maskColor={theme === "dark" ? "rgba(5,5,6,0.75)" : "rgba(241,245,249,0.75)"}
                className="!border !border-border !bg-card/80"
                nodeColor={(n) => riskHex[(n.data as { riskTier: RiskTier }).riskTier]}
              />
            </ReactFlow>
          </Card>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-muted-foreground">
            {TYPE_LEGEND.map(({ type, icon: Icon }) => (
              <span key={type} className="flex items-center gap-1.5">
                <Icon className="h-3.5 w-3.5" />
                {type}
              </span>
            ))}
            <span className="h-3.5 w-px bg-border" />
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-primary" />
              Low failure risk
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-warning" />
              Medium failure risk
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full bg-destructive" />
              High failure risk
            </span>
          </div>

          {selectedNode && (
            <Card className="overflow-hidden p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-display text-base font-semibold text-foreground">{selectedNode.name}</p>
                  <p className="mt-0.5 font-mono-ui text-[11px] uppercase tracking-wider text-muted-foreground">
                    {selectedNode.type} · {selectedNode.status}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedNode(null)}
                  className="font-mono-ui text-xs text-muted-foreground hover:text-foreground"
                >
                  Close
                </button>
              </div>

              <div className="mt-4">
                <div className="flex items-center justify-between font-mono-ui text-[11px] text-muted-foreground">
                  <span>Failure risk</span>
                  <span className="font-semibold text-foreground">
                    {Math.round(selectedNode.failure_probability * 100)}% · {riskTier(selectedNode.failure_probability)}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-secondary">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${Math.round(selectedNode.failure_probability * 100)}%`,
                      background: riskHex[riskTier(selectedNode.failure_probability)],
                    }}
                  />
                </div>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-4 text-sm text-muted-foreground sm:grid-cols-3">
                <Field label="Business value" value={selectedNode.business_value} />
                <Field label="Migration complexity" value={selectedNode.migration_complexity} />
                <Field label="Annual hosting cost" value={`$${selectedNode.annual_cost.toLocaleString()}`} />
                <Field label="Base migration cost" value={`$${selectedNode.base_cost.toLocaleString()}`} />
                <Field label="Base duration" value={`${selectedNode.base_duration} days`} />
                {selectedNode.runtime && <Field label="Runtime" value={selectedNode.runtime} />}
              </dl>

              {(upstream.length > 0 || downstream.length > 0) && (
                <div className="mt-5 grid grid-cols-1 gap-4 border-t border-border pt-4 sm:grid-cols-2">
                  <ConnectionList title="Upstream dependencies" edges={upstream} pick="source" nameById={nameById} />
                  <ConnectionList title="Downstream impact" edges={downstream} pick="target" nameById={nameById} />
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-foreground">{value}</dd>
    </div>
  );
}

function ConnectionList({
  title,
  edges,
  pick,
  nameById,
}: {
  title: string;
  edges: DependencyEdge[];
  pick: "source" | "target";
  nameById: Map<string, string>;
}) {
  if (edges.length === 0) return null;
  return (
    <div>
      <p className="font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground">{title}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {edges.map((e, i) => {
          const id = e[pick];
          const critical = e.criticality === "High";
          return (
            <span
              key={i}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs font-medium",
                critical ? "border-[#DA0037]/40 bg-[#DA0037]/10 text-[#ff5c86]" : "border-border bg-secondary text-foreground/80",
              )}
            >
              {nameById.get(id) ?? id}
            </span>
          );
        })}
      </div>
    </div>
  );
}
