import { useEffect, useRef, useState, type FormEvent } from "react";
import { Send, Sparkles, X } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { ApiError, v1Api } from "@/lib/api";
import type { Assessment, AssessmentGraphResponse, ReportResponse, SimulationResultResponse } from "@/types/api";

interface CopilotMessage {
  role: "user" | "assistant";
  content: string;
}

interface CopilotContext {
  assessment: Assessment | null;
  report: ReportResponse | null;
  graph: AssessmentGraphResponse | null;
  simulation: SimulationResultResponse | null;
}

const EMPTY_CONTEXT: CopilotContext = { assessment: null, report: null, graph: null, simulation: null };

function formatMoney(n: number): string {
  return `$${Math.round(n).toLocaleString()}`;
}

/** Deterministic, keyword-driven, client-side-only responder - the OFFLINE
 * FALLBACK used only if the real chat call (POST .../chat, document-grounded
 * via RAG - see handleSend below) fails, e.g. a network error. Not the
 * primary path anymore; kept so the widget still degrades gracefully to
 * *something* useful, pulling from whatever assessment data is already
 * loaded client-side, rather than a bare error message. */
function answerQuestion(question: string, ctx: CopilotContext): string {
  const q = question.toLowerCase();
  const name = ctx.assessment?.project_name ?? "this assessment";

  if (/\b(hi|hello|hey)\b/.test(q)) {
    return `Hello. I'm the Executive Decision Copilot for ${name}. Ask me about migration risk, cost, timeline, or readiness and I'll pull from the latest assessment data.`;
  }

  if (/risk|risky|danger|threat/.test(q)) {
    if (ctx.graph && ctx.graph.nodes.length > 0) {
      const high = ctx.graph.nodes.filter((n) => n.migration_complexity === "High");
      if (high.length > 0) {
        return `${high.length} of ${ctx.graph.nodes.length} systems carry High migration complexity, including ${high
          .slice(0, 3)
          .map((n) => n.name)
          .join(", ")}. I'd sequence these into later waves with extra rollback planning.`;
      }
      return `None of the ${ctx.graph.nodes.length} systems in the current topology are flagged High complexity - risk looks manageable, but check the What-If Simulation for cascading failure exposure.`;
    }
    return "No topology is saved yet - upload one on the Digital Twin Graph tab and I can break down risk by system.";
  }

  if (/cost|budget|spend|expensive|saving/.test(q)) {
    if (ctx.simulation) {
      return `The last simulation estimated ${formatMoney(
        ctx.simulation.total_hosting_cost,
      )} in current annual hosting cost, with ${formatMoney(
        ctx.simulation.potential_savings,
      )} in potential savings and ${formatMoney(ctx.simulation.revenue_at_risk)} of revenue at risk if the target service fails mid-migration.`;
    }
    if (ctx.graph && ctx.graph.nodes.length > 0) {
      const total = ctx.graph.nodes.reduce((sum, n) => sum + (n.annual_cost ?? 0), 0);
      return `Across ${ctx.graph.nodes.length} systems, current annual hosting cost totals roughly ${formatMoney(
        total,
      )}. Run a What-If Simulation for savings and revenue-at-risk estimates.`;
    }
    return "I don't have cost data yet - save a topology or run a simulation first.";
  }

  if (/timeline|how long|duration|schedule|when/.test(q)) {
    if (ctx.graph && ctx.graph.nodes.length > 0) {
      const totalDays = ctx.graph.nodes.reduce((sum, n) => sum + (n.base_duration ?? 0), 0);
      return `Summed sequentially, the ${ctx.graph.nodes.length} known systems represent about ${totalDays} engineering-days of migration effort - real elapsed time will be shorter once the Wave Planner parallelizes independent systems.`;
    }
    return "No timeline data yet - the Wave Planner will estimate this once a topology is saved and the planning agents have run.";
  }

  if (/wave|sequence|order|planner/.test(q)) {
    return "Open the Wave Planner tab to see how the Discovery, Dependency, Risk, and Planner agents sequence systems into migration waves, with rationale for each grouping.";
  }

  if (/readiness|score|ready/.test(q)) {
    if (ctx.report) {
      return `Current readiness score is ${ctx.report.readiness_score}/100. ${ctx.report.executive_summary}`;
    }
    return "No report has been generated yet - visit the Report tab and generate one to get a readiness score.";
  }

  if (/recommend|next step|advice|suggest/.test(q)) {
    if (ctx.report?.recommendations?.length) {
      return `Top recommendations: ${ctx.report.recommendations.slice(0, 3).join("; ")}.`;
    }
    return "Generate a report first on the Report tab - I'll summarize its recommendations here.";
  }

  return `I can help with questions about risk, cost, timeline, migration waves, or readiness for ${name}. Try asking one of those, or open the relevant tab in the sidebar.`;
}

/** Assistant popup available across every assessment page - opened via a
 * button placed in AppShell's sidebar (see AppShell.tsx), not a floating
 * action button of its own; `open`/`onOpenChange` are lifted up there so the
 * trigger can live in the nav while this component only owns the panel.
 * Wired to a real, document-grounded (RAG) chat endpoint scoped to this
 * assessment (POST .../chat - see app/services_v1/chat_service.py): retrieves
 * relevant chunks from the assessment's own uploaded documents plus a digital
 * twin/report/simulation summary, and asks an LLM to answer grounded in that
 * context. Falls back to the local keyword-driven answerQuestion() above only
 * if the network call itself fails. */
export function ExecutiveCopilot({
  assessmentId,
  open,
  onOpenChange,
}: {
  assessmentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [context, setContext] = useState<CopilotContext>(EMPTY_CONTEXT);
  const [contextLoaded, setContextLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Clicking anywhere outside the panel closes it - but the component itself
  // (and its `messages` state) stays mounted regardless of `open` the whole
  // time this assessment is active (see AppShell, which renders this
  // unconditionally whenever assessmentId is set), so the conversation is
  // still there next time it's reopened. The trigger button(s) in AppShell
  // are excluded via `[data-copilot-trigger]` so clicking them just toggles
  // normally instead of closing-then-immediately-reopening.
  useEffect(() => {
    if (!open) return;
    function handlePointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (panelRef.current?.contains(target)) return;
      if (target instanceof Element && target.closest("[data-copilot-trigger]")) return;
      onOpenChange(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (!open || contextLoaded) return;
    let cancelled = false;

    async function loadContext() {
      const [assessment, report, graph, simulation] = await Promise.all([
        v1Api.getAssessment(assessmentId).catch(() => null),
        v1Api.getReport(assessmentId).catch(() => null),
        v1Api.getAssessmentGraph(assessmentId).catch(() => null),
        v1Api.getSimulation(assessmentId).catch(() => null),
      ]);
      if (cancelled) return;
      setContext({ assessment, report, graph, simulation });
      setContextLoaded(true);
      setMessages([
        {
          role: "assistant",
          content: `Hello. I'm the Executive Decision Copilot${
            assessment ? ` for ${assessment.project_name}` : ""
          }. Ask me about migration risk, cost, timeline, or readiness.`,
        },
      ]);
    }

    loadContext();
    return () => {
      cancelled = true;
    };
  }, [open, contextLoaded, assessmentId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setInput("");
    setThinking(true);
    try {
      const response = await v1Api.assessmentChat(assessmentId, history);
      setMessages((prev) => [...prev, { role: "assistant", content: response.reply }]);
    } catch (err) {
      // Network/backend failure - degrade to the local keyword-driven
      // responder rather than showing a raw error in the chat.
      const message = err instanceof ApiError ? err.message : null;
      const fallback = answerQuestion(text, context);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: message ? `${fallback}\n\n(${message})` : fallback },
      ]);
    } finally {
      setThinking(false);
    }
  }

  return (
    <>
      {open && (
        <div
          ref={panelRef}
          className="fixed bottom-6 left-4 z-40 flex h-[520px] w-[380px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border bg-card/50 shadow-2xl shadow-black/50 backdrop-blur-2xl lg:left-80"
        >
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E]">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-foreground">Executive Decision Copilot</p>
              <p className="truncate text-[11px] text-muted-foreground">Grounded in this assessment's documents</p>
            </div>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="shrink-0 text-muted-foreground transition hover:text-foreground"
              aria-label="Close Executive Decision Copilot"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "bg-primary text-primary-foreground dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E]"
                      : "border border-border bg-muted/30 text-foreground/90"
                  }`}
                >
                  {m.role === "assistant" ? (
                    <Markdown text={m.content} className="text-foreground/90" />
                  ) : (
                    m.content
                  )}
                </div>
              </div>
            ))}
            {thinking && (
              <div className="flex justify-start">
                <div className="rounded-2xl border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
                  Thinking...
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleSend} className="flex items-center gap-2 border-t border-border p-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about risk, cost, timeline..."
              className="flex-1 rounded-lg border border-border bg-input/30 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
            />
            <Button type="submit" size="icon" disabled={!input.trim()} aria-label="Send">
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      )}
    </>
  );
}
