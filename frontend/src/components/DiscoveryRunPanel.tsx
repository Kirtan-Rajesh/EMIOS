import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Loader2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/Card";
import { useDiscoveryRun } from "@/lib/discovery-run-context";
import { describeDiscoveryEvent } from "@/lib/discovery-events";

const AUTO_HIDE_MS = 10_000;

/** Side panel showing Document Discovery's live progress while a
 * background run (started from DocumentsPage or NewAssessmentPage) is in
 * progress - visible on every page since DiscoveryRunProvider lives at the
 * app root, not scoped to one route. Mirrors PlannerRunPanel exactly; both
 * are stacked together in the bottom-right notification column mounted once
 * in App.tsx (this component just returns the Card, not the fixed wrapper).
 *
 * Once the run finishes (complete/error), auto-dismisses after AUTO_HIDE_MS
 * if the user never interacts with it - any click inside the panel cancels
 * the pending auto-hide, on the assumption interacting with it means the
 * user has seen it. */
export function DiscoveryRunPanel() {
  const { assessmentId, status, events, errorMessage, dismiss } = useDiscoveryRun();
  const [collapsed, setCollapsed] = useState(false);
  const autoHideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (status !== "complete" && status !== "error") return;
    autoHideTimer.current = setTimeout(dismiss, AUTO_HIDE_MS);
    return () => {
      if (autoHideTimer.current) clearTimeout(autoHideTimer.current);
    };
  }, [status, dismiss]);

  function cancelAutoHide() {
    if (autoHideTimer.current) {
      clearTimeout(autoHideTimer.current);
      autoHideTimer.current = null;
    }
  }

  if (status === "idle" || !assessmentId) return null;

  return (
    <Card className="overflow-hidden border-primary/20 bg-card/40 shadow-2xl" onClick={cancelAutoHide}>
      <div className="flex items-center gap-2 border-b border-border/60 p-3">
        {status === "running" && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />}
        {status === "complete" && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />}
        {status === "error" && <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />}
        <span className="flex-1 truncate text-sm font-medium text-foreground">
          {status === "running" && "Processing documents..."}
          {status === "complete" && "Document processing finished"}
          {status === "error" && "Document processing failed"}
        </span>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="shrink-0 text-muted-foreground transition hover:text-foreground"
          aria-label={collapsed ? "Show details" : "Hide details"}
        >
          {collapsed ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 text-muted-foreground transition hover:text-foreground"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {!collapsed && (
        <div className="max-h-72 space-y-1 overflow-y-auto p-3 font-mono text-[11px] text-muted-foreground">
          {events.length === 0 && status === "running" && <p>Starting...</p>}
          {events.map((event, i) => (
            <p key={i} className={event.type === "error" ? "text-destructive" : undefined}>
              {describeDiscoveryEvent(event)}
            </p>
          ))}

          {status === "error" && errorMessage && <p className="text-destructive">{errorMessage}</p>}

          {status === "complete" && (
            <Link
              to={`/assessments/${assessmentId}/graph`}
              onClick={dismiss}
              className="mt-2 block rounded-lg bg-primary px-3 py-2 text-center text-xs font-semibold text-primary-foreground shadow-sm transition dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E] dark:shadow-lg dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
            >
              View digital twin
            </Link>
          )}
        </div>
      )}
    </Card>
  );
}
