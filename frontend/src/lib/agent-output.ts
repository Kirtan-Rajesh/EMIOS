import type { AgentRunResponse } from "@/types/api";

// Every agent prompt asks for "strict JSON, no markdown fences," but models
// routinely ignore that and wrap the response in ```json ... ``` anyway.
// Stripping is done here (client-side) rather than assumed to already be
// clean server-side - app/core/llm_provider.py's own centralized stripping
// for this has been added and removed at least once already, so this parse
// path shouldn't depend on the backend having done it first.
//
// No `m` (multiline) flag: this must only strip a fence wrapping the *whole*
// message, not any ``` -fenced block that happens to appear mid-text - the
// Planner Agent's message in particular is prose + an embedded ```mermaid
// wave-flowchart block + more prose (app/agents/response_formatter.py's
// format_planner()), not a single JSON blob. With `m`, `^`/`$` anchor to
// every line instead of the string's true start/end, so this used to strip
// the ```mermaid fence's backticks wherever they landed - leaving the bare
// word "mermaid" as stray text and destroying the fence markers
// Markdown.tsx's `pre` renderer needs to recognize the block at all, so it
// rendered as flattened plain-paragraph text instead of a diagram.
const CODE_FENCE_RE = /^```(?:json)?\s*|\s*```$/g;

function stripCodeFence(text: string): string {
  return text.trim().replace(CODE_FENCE_RE, "").trim();
}

/** Extracts a human-readable message from one agent run's summary - shared by
 * PlannerPage's Explainability view and the global PlannerRunPanel side
 * panel, so both parse the exact same shape the same way.
 *
 * The raw `summary.message` field is sometimes the agent's full structured
 * JSON output (waves/objections/risk_assessment/etc - see the *AgentOutput
 * types) rather than prose, if the LLM answered the "return this JSON shape"
 * part of its prompt but the caller only stored the raw completion text under
 * `message` - showing that raw JSON (or worse, JSON still wrapped in ```
 * fences) in a notification panel reads as broken. Every agent output shape
 * includes a narrative `agent_log` string field specifically for this display
 * purpose, so when the message parses as JSON, prefer that field over the
 * raw blob. */
/** Whether this negotiation-log entry's LLM call actually got a real model
 * response or fell through to the deterministic fallback text - see
 * `_log_source` in backend/app/agents/workflow.py, which is what stamps this
 * field onto `run.summary`. Absent (null) for runs recorded before this field
 * existed, or for the legacy 4-agent run_planner() path's rows - callers
 * should treat that the same as "unknown," not as "definitely real." */
export function agentLogSource(run: AgentRunResponse): "llm" | "fallback" | null {
  const summary = run.summary;
  if (!summary || typeof summary !== "object" || !("source" in summary)) return null;
  const source = (summary as { source?: unknown }).source;
  return source === "llm" || source === "fallback" ? source : null;
}

export function agentMessage(run: AgentRunResponse): string {
  const summary = run.summary;
  if (!summary || typeof summary !== "object" || !("message" in summary)) return "";
  const raw = String((summary as { message?: string }).message ?? "");

  const parsed = tryParseAgentOutput<{ agent_log?: string }>(raw);
  if (parsed && typeof parsed.agent_log === "string" && parsed.agent_log.trim()) {
    return parsed.agent_log;
  }
  // Parsing failed (or had no agent_log) - still strip any fence wrapper so a
  // raw JSON dump doesn't at least show the ``` markers literally.
  return stripCodeFence(raw);
}

/** Full raw message text (fence-stripped only, no agent_log extraction) - for
 * PlannerPage's per-agent Explainer components, which each need the *whole*
 * structured object (executive_summary/key_takeaways/orphans_found/waves/etc,
 * not just the narrative log) to do their own complete parse. Using
 * agentMessage() here instead would be wrong: whenever an agent reliably
 * fills in agent_log (e.g. the Report Generation Agent, whose entire job is
 * narrative writing), agentMessage() returns *only* that narrative string,
 * so the Explainer's own tryParseAgentOutput call re-parses plain prose as
 * JSON, fails, and falls back to dumping it raw - losing executive_summary/
 * key_takeaways entirely. agentMessage() stays as-is for PlannerRunPanel,
 * which really does just want the short narrative snippet. */
export function agentRawMessage(run: AgentRunResponse): string {
  const summary = run.summary;
  if (!summary || typeof summary !== "object" || !("message" in summary)) return "";
  return stripCodeFence(String((summary as { message?: string }).message ?? ""));
}

/** Escapes literal control characters (raw newlines/tabs/carriage returns)
 * that appear *inside* JSON string literals - models routinely emit
 * multi-paragraph fields (executive_summary especially) with real newlines
 * instead of `\n`, which is invalid per the JSON spec and makes JSON.parse
 * throw on an otherwise well-formed payload. Only touches characters between
 * unescaped quotes so it can't corrupt the surrounding JSON structure. */
function escapeControlCharsInStrings(text: string): string {
  let result = "";
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"' && text[i - 1] !== "\\") inString = !inString;
    if (inString) {
      if (ch === "\n") { result += "\\n"; continue; }
      if (ch === "\r") { result += "\\r"; continue; }
      if (ch === "\t") { result += "\\t"; continue; }
    }
    result += ch;
  }
  return result;
}

/** Best-effort parse of an agent's raw message as structured JSON - the LLM is
 * prompted to return this shape, but it's never schema-enforced (the
 * deterministic no-provider-configured fallback returns plain prose instead),
 * so a failed parse just means "render the raw text instead". Strips a
 * ```json ... ``` wrapper first, since that alone would otherwise fail
 * JSON.parse even though the content inside is perfectly valid. Falls back to
 * a sanitized re-parse (see escapeControlCharsInStrings) before giving up,
 * since a raw-newline-in-a-string failure is otherwise indistinguishable from
 * genuinely non-JSON prose. */
export function tryParseAgentOutput<T>(message: string): T | null {
  const stripped = stripCodeFence(message);
  try {
    const parsed: unknown = JSON.parse(stripped);
    return parsed && typeof parsed === "object" ? (parsed as T) : null;
  } catch {
    try {
      const parsed: unknown = JSON.parse(escapeControlCharsInStrings(stripped));
      return parsed && typeof parsed === "object" ? (parsed as T) : null;
    } catch {
      return null;
    }
  }
}
