import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, v1Api } from "@/lib/api";
import { usePlannerRun } from "@/lib/planner-run-context";
import type { ReportResponse } from "@/types/api";

export type ReportRunStatus = "idle" | "running" | "complete" | "error";

interface ReportRunState {
  assessmentId: string | null;
  status: ReportRunStatus;
  result: ReportResponse | null;
  errorMessage: string | null;
}

interface ReportRunContextValue extends ReportRunState {
  startRun: (assessmentId: string) => void;
  dismiss: () => void;
}

const ReportRunContext = createContext<ReportRunContextValue | null>(null);

const IDLE_STATE: ReportRunState = {
  assessmentId: null,
  status: "idle",
  result: null,
  errorMessage: null,
};

/** Generates the executive report (POST .../report - a single narrative LLM
 * call, not a stream) in the background, independent of whatever page the
 * user is on - mirrors PlannerRunProvider/DiscoveryRunProvider exactly, down
 * to the toast-on-completion. Mounted inside PlannerRunProvider (see
 * App.tsx) specifically so the effect below can watch usePlannerRun() and
 * auto-start a report the moment a planner run finishes - chaining Discovery
 * -> Planner -> Report all automatically, the same way Planner already
 * auto-starts once Discovery builds a graph (see OverviewPage's
 * autoStartPlanner). Previously report generation only ever started when the
 * user happened to land on the Report tab (ReportPage's own
 * getReport().catch(handleGenerateReport)) - by the time they get there now,
 * it's typically already done. */
export function ReportRunProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const plannerRun = usePlannerRun();
  const [state, setState] = useState<ReportRunState>(IDLE_STATE);
  const abortRef = useRef<{ assessmentId: string; cancelled: boolean } | null>(null);
  // Guards against re-firing for the same completed planner run - usePlannerRun()'s
  // state stays "complete" long after the transition itself, so without this,
  // any unrelated re-render would restart report generation from scratch.
  const autoStartedForRef = useRef<string | null>(null);

  const startRun = useCallback(
    (assessmentId: string) => {
      if (abortRef.current) abortRef.current.cancelled = true;
      const marker = { assessmentId, cancelled: false };
      abortRef.current = marker;

      setState({ ...IDLE_STATE, assessmentId, status: "running" });

      v1Api
        .generateReport(assessmentId)
        .then((result) => {
          if (marker.cancelled) return;
          setState((prev) => (prev.assessmentId === assessmentId ? { ...prev, status: "complete", result } : prev));
          toast.success("Report generated.", {
            action: { label: "View", onClick: () => navigate(`/assessments/${assessmentId}/report`) },
            duration: 15000,
          });
        })
        .catch((err) => {
          if (marker.cancelled) return;
          const message = err instanceof ApiError ? err.message : "Could not generate the report.";
          setState((prev) =>
            prev.assessmentId === assessmentId ? { ...prev, status: "error", errorMessage: message } : prev,
          );
          toast.error(message);
        });
    },
    [navigate],
  );

  useEffect(() => {
    if (
      plannerRun.status === "complete" &&
      plannerRun.assessmentId &&
      autoStartedForRef.current !== plannerRun.assessmentId
    ) {
      autoStartedForRef.current = plannerRun.assessmentId;
      startRun(plannerRun.assessmentId);
    }
  }, [plannerRun.status, plannerRun.assessmentId, startRun]);

  const dismiss = useCallback(() => {
    if (abortRef.current) abortRef.current.cancelled = true;
    setState(IDLE_STATE);
  }, []);

  return (
    <ReportRunContext.Provider value={{ ...state, startRun, dismiss }}>{children}</ReportRunContext.Provider>
  );
}

export function useReportRun(): ReportRunContextValue {
  const ctx = useContext(ReportRunContext);
  if (!ctx) throw new Error("useReportRun must be used within a ReportRunProvider");
  return ctx;
}
