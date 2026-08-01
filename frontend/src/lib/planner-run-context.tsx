import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, v1Api } from "@/lib/api";
import { agentRawMessage, tryParseAgentOutput } from "@/lib/agent-output";
import type {
  AgentRunResponse,
  PlannerAgentOutput,
  PlannerStreamEvent,
  RunPlannerResponse,
  WaveItem,
} from "@/types/api";

/** Persists a finished planner run's waves to the Migration Waves module
 * (POST .../waves) so OverviewPage's "Migration wave plan" chart - which
 * reads only the persisted migration_waves table via GET .../waves, entirely
 * separate from the agent_runs-backed data PlannerPage itself renders - has
 * something to show. Without this call the wave chart stayed empty forever:
 * nothing else in the app ever wrote to that table. rationale is a required
 * field on the wave-create contract; the planner negotiation only produces
 * one, run-wide "adjustments_made" list (inside the Planner Agent's own
 * structured output) rather than a per-wave one, so it's reused across every
 * wave from this run. */
async function persistPlannerWaves(
  assessmentId: string,
  waves: string[][],
  riskAssessment: Record<string, unknown>,
  agentRuns: AgentRunResponse[],
): Promise<void> {
  if (waves.length === 0) return;

  const plannerRun = agentRuns.find((r) => r.agent_name === "Planner Agent");
  const adjustments = plannerRun
    ? tryParseAgentOutput<PlannerAgentOutput>(agentRawMessage(plannerRun))?.adjustments_made
    : undefined;
  const rationale = adjustments?.length
    ? adjustments.join(" ")
    : "Produced by the Discovery/Dependency/Planner/Risk agent negotiation.";

  const items: WaveItem[] = waves.map((components, i) => ({
    wave_number: i + 1,
    components,
    rationale,
    risk_summary: Object.fromEntries(
      Object.entries(riskAssessment ?? {}).filter(([component]) => components.includes(component)),
    ),
  }));

  try {
    await v1Api.createWaves(assessmentId, items);
  } catch (err) {
    // A 409 means this assessment already has a stored wave plan (there is no
    // replace/update endpoint yet - each wave_number can only be created once
    // per assessment, see WaveService.create_waves) - a re-run's new plan just
    // can't overwrite it, but Overview still has the earlier one to show, so
    // this isn't worth surfacing. Anything else means the wave chart will
    // stay empty and the user should know why.
    if (!(err instanceof ApiError) || err.status !== 409) {
      toast.error("Planner finished, but the wave plan couldn't be saved for the Overview dashboard.");
    }
  }
}

export type PlannerRunStatus = "idle" | "running" | "complete" | "error";

interface PlannerRunState {
  assessmentId: string | null;
  status: PlannerRunStatus;
  events: AgentRunResponse[];
  result: RunPlannerResponse | null;
  errorMessage: string | null;
  reasoningHidden: boolean;
}

interface PlannerRunContextValue extends PlannerRunState {
  startRun: (assessmentId: string) => void;
  toggleReasoningHidden: () => void;
  dismiss: () => void;
}

const PlannerRunContext = createContext<PlannerRunContextValue | null>(null);

const IDLE_STATE: PlannerRunState = {
  assessmentId: null,
  status: "idle",
  events: [],
  result: null,
  errorMessage: null,
  reasoningHidden: false,
};

/** Runs the multi-agent planner (Discovery/Dependency/Planner/Risk
 * negotiation) in the background, independent of whatever page the user is
 * currently on - mounted once at the app root (see App.tsx) so the live
 * reasoning stream, and the completion notification, survive client-side
 * route changes. Started automatically once Document Discovery finishes
 * building a graph (see NewAssessmentPage -> OverviewPage), or manually via
 * PlannerPage's "Run planner" button. Only one run is tracked at a time -
 * starting a new one (a different assessment, or a manual re-run) replaces
 * whatever was being shown. */
export function PlannerRunProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [state, setState] = useState<PlannerRunState>(IDLE_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const startRun = useCallback(
    (assessmentId: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setState({ ...IDLE_STATE, assessmentId, status: "running" });

      // Mirrors prev.events but readable synchronously from the "complete"
      // branch below (a setState updater can't run the async persist call
      // itself) without waiting on a render round-trip.
      let latestEvents: AgentRunResponse[] = [];

      v1Api
        .streamPlanner(
          assessmentId,
          (event: PlannerStreamEvent) => {
            if (event.type === "agent_result") {
              const { type: _type, ...run } = event;
              latestEvents = [...latestEvents, run];
              setState((prev) => (prev.assessmentId === assessmentId ? { ...prev, events: latestEvents } : prev));
            } else if (event.type === "complete") {
              setState((prev) => {
                if (prev.assessmentId !== assessmentId) return prev;
                const { type: _type, ...pipelineFields } = event;
                return {
                  ...prev,
                  status: "complete",
                  result: {
                    ...pipelineFields,
                    agent_runs: prev.events,
                  },
                };
              });
              toast.success("Planner agents finished negotiating the migration plan.", {
                action: { label: "View", onClick: () => navigate(`/assessments/${assessmentId}/planner`) },
                duration: 15000,
              });
              void persistPlannerWaves(assessmentId, event.waves, event.risk_assessment, latestEvents);
            } else if (event.type === "error") {
              setState((prev) =>
                prev.assessmentId === assessmentId
                  ? { ...prev, status: "error", errorMessage: event.message }
                  : prev,
              );
              toast.error(`Planner run failed: ${event.message}`);
            }
          },
          controller.signal,
        )
        .catch((err) => {
          if (controller.signal.aborted) return;
          const message = err instanceof ApiError ? err.message : "Planner run failed.";
          setState((prev) =>
            prev.assessmentId === assessmentId ? { ...prev, status: "error", errorMessage: message } : prev,
          );
          toast.error(message);
        });
    },
    [navigate],
  );

  const toggleReasoningHidden = useCallback(() => {
    setState((prev) => ({ ...prev, reasoningHidden: !prev.reasoningHidden }));
  }, []);

  const dismiss = useCallback(() => {
    abortRef.current?.abort();
    setState(IDLE_STATE);
  }, []);

  return (
    <PlannerRunContext.Provider value={{ ...state, startRun, toggleReasoningHidden, dismiss }}>
      {children}
    </PlannerRunContext.Provider>
  );
}

export function usePlannerRun(): PlannerRunContextValue {
  const ctx = useContext(PlannerRunContext);
  if (!ctx) throw new Error("usePlannerRun must be used within a PlannerRunProvider");
  return ctx;
}
