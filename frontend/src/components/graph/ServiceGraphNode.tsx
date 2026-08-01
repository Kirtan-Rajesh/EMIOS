import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Boxes, Database, ListOrdered, Server, CircleDot, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type RiskTier = "low" | "med" | "high";

export interface ServiceGraphNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  riskTier: RiskTier;
  riskPct: number;
  dimmed: boolean;
  active: boolean;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  Monolith: Server,
  Database: Database,
  Microservice: Boxes,
  Queue: ListOrdered,
};

// Ring/dot use the semantic tokens (theme-correct in both light and dark -
// see index.css's :root/.dark). The neon drop-shadow "glow" on hover/active
// is dark theme's mission-control character specifically, not part of the
// light theme's flatter look, so it only ever applies via dark:.
const RISK_STYLE: Record<RiskTier, { ring: string; dot: string; glow: string }> = {
  low: { ring: "border-primary/45", dot: "bg-primary", glow: "dark:shadow-[0_0_18px_-4px_#30E3CA]" },
  med: { ring: "border-warning/50", dot: "bg-warning", glow: "dark:shadow-[0_0_18px_-4px_#FFB020]" },
  high: { ring: "border-destructive/60", dot: "bg-destructive", glow: "dark:shadow-[0_0_18px_-4px_#DA0037]" },
};

function ServiceGraphNodeImpl({ data, selected }: NodeProps) {
  const d = data as ServiceGraphNodeData;
  const Icon = TYPE_ICON[d.nodeType] ?? CircleDot;
  const risk = RISK_STYLE[d.riskTier];

  return (
    <div
      className={cn(
        "flex w-[190px] items-center gap-2.5 rounded-xl border bg-card/70 px-3 py-2.5 backdrop-blur-md transition-all duration-200",
        risk.ring,
        d.active && cn("scale-[1.05] bg-card/90", risk.glow),
        d.dimmed && "opacity-25",
        selected && "ring-2 ring-offset-0 ring-[color:var(--ring)]",
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-none !bg-border" />
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono-ui text-[11.5px] font-semibold leading-tight text-foreground">
          {d.label}
        </span>
        <span className="mt-0.5 block truncate font-mono-ui text-[9px] uppercase tracking-wider text-muted-foreground">
          {d.nodeType}
        </span>
      </span>
      <span className="relative flex h-2.5 w-2.5 shrink-0 items-center justify-center" title={`${d.riskPct}% failure risk`}>
        <span className={cn("h-2 w-2 rounded-full", risk.dot)} />
      </span>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-none !bg-border" />
    </div>
  );
}

export const ServiceGraphNode = memo(ServiceGraphNodeImpl);
