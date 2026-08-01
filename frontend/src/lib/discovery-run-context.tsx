import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, v1Api } from "@/lib/api";
import type { DiscoveryEvent } from "@/types/api";

export type DiscoveryRunStatus = "idle" | "running" | "complete" | "error";

interface DiscoveryRunState {
  assessmentId: string | null;
  status: DiscoveryRunStatus;
  events: DiscoveryEvent[];
  errorMessage: string | null;
}

interface DiscoveryRunContextValue extends DiscoveryRunState {
  startRun: (assessmentId: string) => void;
  dismiss: () => void;
}

const DiscoveryRunContext = createContext<DiscoveryRunContextValue | null>(null);

const IDLE_STATE: DiscoveryRunState = {
  assessmentId: null,
  status: "idle",
  events: [],
  errorMessage: null,
};

/** Runs Document Discovery (extract systems/dependencies from uploaded
 * documents -> auto-persist the digital twin graph) in the background,
 * independent of whatever page the user is currently on - mounted once at
 * the app root (see App.tsx), mirroring PlannerRunProvider's pattern exactly,
 * so the live progress stream and the completion notification survive
 * client-side route changes. Previously this lived in DocumentsPage's local
 * component state, which meant navigating away mid-run (or even just before
 * it) silently lost all visibility into whether it ever finished - the graph
 * would eventually get persisted server-side (or not, if something failed),
 * but nothing on screen would ever reflect it. Only one run is tracked at a
 * time - starting a new one replaces whatever was being shown, same as
 * PlannerRunProvider. */
export function DiscoveryRunProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [state, setState] = useState<DiscoveryRunState>(IDLE_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const startRun = useCallback(
    (assessmentId: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setState({ ...IDLE_STATE, assessmentId, status: "running" });
      toast("Processing documents in the background...", {
        description: "Feel free to navigate away - you'll be notified here when it's done.",
      });

      v1Api
        .streamDiscovery(
          assessmentId,
          (event: DiscoveryEvent) => {
            setState((prev) => {
              if (prev.assessmentId !== assessmentId) return prev;
              if (event.type === "complete") {
                return { ...prev, status: "complete", events: [...prev.events, event] };
              }
              if (event.type === "error") {
                return { ...prev, status: "error", errorMessage: event.message, events: [...prev.events, event] };
              }
              return { ...prev, events: [...prev.events, event] };
            });

            if (event.type === "complete") {
              if (event.status === "graph_updated") {
                toast.success(
                  `Document processing complete — ${event.node_count} systems, ${event.edge_count} dependencies added to the digital twin.`,
                  {
                    action: { label: "View", onClick: () => navigate(`/assessments/${assessmentId}/graph`) },
                    duration: 15000,
                  },
                );
              } else {
                toast("Document processing finished, but no systems or dependencies could be extracted.");
              }
            } else if (event.type === "error") {
              toast.error(`Document processing failed: ${event.message}`);
            }
          },
          controller.signal,
        )
        .catch((err) => {
          if (controller.signal.aborted) return;
          const message = err instanceof ApiError ? err.message : "Document processing failed.";
          setState((prev) =>
            prev.assessmentId === assessmentId ? { ...prev, status: "error", errorMessage: message } : prev,
          );
          toast.error(message);
        });
    },
    [navigate],
  );

  const dismiss = useCallback(() => {
    abortRef.current?.abort();
    setState(IDLE_STATE);
  }, []);

  return (
    <DiscoveryRunContext.Provider value={{ ...state, startRun, dismiss }}>{children}</DiscoveryRunContext.Provider>
  );
}

export function useDiscoveryRun(): DiscoveryRunContextValue {
  const ctx = useContext(DiscoveryRunContext);
  if (!ctx) throw new Error("useDiscoveryRun must be used within a DiscoveryRunProvider");
  return ctx;
}
