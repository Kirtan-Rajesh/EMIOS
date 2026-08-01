import { useEffect, useRef } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, Loader2, Sparkles, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/Card";
import { agentMessage } from "@/lib/agent-output";
import { usePlannerRun } from "@/lib/planner-run-context";

const AGENT_ORDER = ["Discovery Agent", "Dependency Agent", "Planner Agent", "Risk Agent"];
const AUTO_HIDE_MS = 10_000;

/** Side panel showing the planner agents' live reasoning while a
 * background run (started from NewAssessmentPage/OverviewPage, or manually
 * from the Planner page) is in progress - visible on every page since
 * PlannerRunProvider lives at the app root, not scoped to one route. Collapses
 * to a slim status bar via the chevron toggle ("option to hide the
 * reasoning"); the X fully dismisses it once there's nothing more to show.
 * Stacked together with DiscoveryRunPanel in the bottom-right notification
 * column mounted once in App.tsx (this component just returns the Card, not
 * the fixed wrapper).
 *
 * Once the run finishes (complete/error), auto-dismisses after AUTO_HIDE_MS
 * if the user never interacts with it - any click inside the panel cancels
 * the pending auto-hide. */
export function PlannerRunPanel() {
  const { assessmentId, status, events, errorMessage, reasoningHidden, toggleReasoningHidden, dismiss } =
    usePlannerRun();
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

  const latestByAgent = new Map(events.map((run) => [run.agent_name, run]));

  return (
    <Card className="overflow-hidden border-primary/20 bg-card/40 shadow-2xl" onClick={cancelAutoHide}>
      <div className="flex items-center gap-2 border-b border-border/60 p-3">
        {status === "running" && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />}
        {status === "complete" && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />}
        {status === "error" && <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />}
        <span className="flex-1 truncate text-sm font-medium text-foreground">
          {status === "running" && "Planner agents negotiating..."}
          {status === "complete" && "Planner agents finished"}
          {status === "error" && "Planner run failed"}
        </span>
        <button
          type="button"
          onClick={toggleReasoningHidden}
          className="shrink-0 text-muted-foreground transition hover:text-foreground"
          aria-label={reasoningHidden ? "Show reasoning" : "Hide reasoning"}
        >
          {reasoningHidden ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
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

      {!reasoningHidden && (
        <div className="max-h-96 space-y-2 overflow-y-auto p-3">
          {events.length === 0 && status === "running" && (
            <p className="text-xs text-muted-foreground">Starting Discovery Agent...</p>
          )}
          {AGENT_ORDER.filter((name) => latestByAgent.has(name)).map((name) => {
            const run = latestByAgent.get(name)!;
            return (
              <div key={run.agent_run_id} className="rounded-lg border border-border bg-muted/30 p-2.5 text-xs">
                <p className="flex items-center gap-1.5 font-medium text-foreground">
                  <Sparkles className="h-3 w-3 text-primary" /> {run.agent_name}
                </p>
                <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-muted-foreground">
                  {agentMessage(run) || "Working..."}
                </p>
              </div>
            );
          })}

          {status === "error" && errorMessage && <p className="text-xs text-destructive">{errorMessage}</p>}

          {status === "complete" && (
            <Link
              to={`/assessments/${assessmentId}/planner`}
              onClick={dismiss}
              className="block rounded-lg bg-primary px-3 py-2 text-center text-xs font-semibold text-primary-foreground shadow-sm transition dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E] dark:shadow-lg dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
            >
              View wave plan
            </Link>
          )}
        </div>
      )}
    </Card>
  );
}
