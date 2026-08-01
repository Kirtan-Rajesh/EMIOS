import { Loader2, type LucideIcon } from "lucide-react";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Semantic tone rather than a raw hex color: resolves to this app's
 * theme-variable-backed Tailwind classes (bg-primary/10, etc.), so the
 * icon/badge automatically picks up the right shade for whichever theme
 * (light/dark - see lib/theme-context.tsx) is active, no per-call color math. */
type KpiTone = "primary" | "destructive" | "warning" | "success";

const TONE_CLASSES: Record<KpiTone, string> = {
  primary: "bg-primary/10 text-primary",
  destructive: "bg-destructive/10 text-destructive",
  warning: "bg-warning/10 text-warning",
  success: "bg-success/10 text-success",
};

interface KpiCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  sub: string;
  tone?: KpiTone;
  /** True while the background pipeline this card's value comes from is
   * actively running (e.g. the Wave Planner) and hasn't produced a result
   * yet - shows a pulsing skeleton instead of the empty-state "—"/"run the
   * planner" text, which otherwise reads as "nothing has happened" even
   * while a multi-minute run is genuinely in progress. */
  loading?: boolean;
}

export function KpiCard({ icon: Icon, label, value, sub, tone = "primary", loading }: KpiCardProps) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2.5">
        <div className={cn("inline-flex shrink-0 rounded-lg p-1.5", TONE_CLASSES[tone])}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 text-sm text-muted-foreground">{label}</div>
      </div>
      {loading ? (
        <>
          <Skeleton className="mt-2.5 h-6 w-16" />
          <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> Planner running...
          </div>
        </>
      ) : (
        <>
          <div className="mt-2.5 text-xl font-semibold text-foreground">{value}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>
        </>
      )}
    </Card>
  );
}
