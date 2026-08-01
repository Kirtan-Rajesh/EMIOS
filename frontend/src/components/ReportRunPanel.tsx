import { useEffect, useRef } from "react";
import { AlertTriangle, CheckCircle2, FileText, Loader2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "@/components/Card";
import { useReportRun } from "@/lib/report-run-context";

const AUTO_HIDE_MS = 10_000;

/** Small status card for the background report-generation call (a single
 * POST, not a stream - see report-run-context.tsx), stacked with
 * PlannerRunPanel/DiscoveryRunPanel in the bottom-right notification column
 * mounted once in App.tsx. Simpler than those two since there's no live
 * per-agent reasoning to show - just idle/running/complete/error.
 *
 * Auto-dismisses after AUTO_HIDE_MS once finished, same as the other two
 * panels; any click inside cancels the pending auto-hide. */
export function ReportRunPanel() {
  const { assessmentId, status, errorMessage, dismiss } = useReportRun();
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
          {status === "running" && "Generating report..."}
          {status === "complete" && "Report ready"}
          {status === "error" && "Report generation failed"}
        </span>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 text-muted-foreground transition hover:text-foreground"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="space-y-2 p-3">
        {status === "running" && (
          <p className="text-xs text-muted-foreground">
            Writing the executive summary from the planner's readiness, risk, and strategy output...
          </p>
        )}
        {status === "error" && errorMessage && <p className="text-xs text-destructive">{errorMessage}</p>}
        {status === "complete" && (
          <Link
            to={`/assessments/${assessmentId}/report`}
            onClick={dismiss}
            className="flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-center text-xs font-semibold text-primary-foreground shadow-sm transition dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E] dark:shadow-lg dark:shadow-[#FF204E]/25 dark:hover:shadow-[#FF204E]/40"
          >
            <FileText className="h-3.5 w-3.5" /> View report
          </Link>
        )}
      </div>
    </Card>
  );
}
