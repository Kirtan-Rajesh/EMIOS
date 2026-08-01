/**
 * Thin fetch wrappers around the two real EMIOS backend API surfaces.
 *
 *  - `legacyApi` targets `/api/*`   (unwrapped responses) - kept for reference,
 *    not used by this app; the demo UI it powered has been retired in favor of
 *    the sequence-driven flow below, but the surface itself stays live.
 *  - `v1Api`     targets `/api/v1/*` (envelope responses: {success, message, data})
 *
 * In dev, Vite proxies `/api` -> http://localhost:8000 (see vite.config.ts).
 * In production these are same-origin requests since FastAPI serves the built
 * SPA from frontend/dist.
 */
import type {
  AgentRunResponse,
  Assessment,
  AssessmentChatResponse,
  AssessmentCreateRequest,
  AssessmentGraphResponse,
  AssessmentStatus,
  AssessmentUpload,
  AuthResponse,
  ChatMessage,
  ChatResponse,
  CurrentUserResponse,
  DashboardSummary,
  DiscoveryEvent,
  GraphData,
  GraphPersistResponse,
  LoginRequest,
  MigrationWave,
  PlannerStreamEvent,
  PlanningResponse,
  RegisterRequest,
  ReportFeedbackRequest,
  ReportResponse,
  ReportReviseRequest,
  ReportRevisionDetail,
  ReportRevisionSummary,
  ReviseReportResponse,
  RunPlannerResponse,
  SimulateRequest,
  SimulationRequest,
  SimulationResponse,
  SimulationResultResponse,
  UploadResponseLegacy,
  WaveItem,
  ZipStreamEvent,
  ZipUploadResponse,
} from "@/types/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  // Auth is an httpOnly session cookie set by the backend (app/api/v1/auth.py) -
  // this client never reads or attaches the token itself (that's the whole
  // point: an XSS payload running in this page can no longer read a
  // JS-visible token, unlike the old localStorage approach). `credentials:
  // "include"` is what makes the browser actually send/accept that cookie.
  const res = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await res.json().catch(() => null) : null;

  if (!res.ok) {
    const message =
      (body && (body.message || body.error_code || body.detail)) ||
      `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status);
  }
  return body as T;
}

async function requestEnvelope<T>(url: string, init?: RequestInit): Promise<T> {
  const body = await request<{ success: boolean; message: string; data?: T; errors?: string[] }>(
    url,
    init,
  );
  if (!body.success) {
    throw new ApiError(body.errors?.join(", ") || body.message || "Request failed", 500);
  }
  return body.data as T;
}

/**
 * Reads a `text/event-stream` response body (Server-Sent Events) as it
 * arrives, calling `onLine` with each event's raw `data:` payload. Hand-rolled
 * rather than the native `EventSource` API: EventSource is GET-only, and this
 * app streams the planner/discovery runs via POST - a plain `fetch()` with a
 * streamed body works for any method.
 */
async function streamSse(
  url: string,
  init: RequestInit,
  onLine: (data: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    ...init,
    credentials: "include",
    signal,
  });

  if (!res.ok || !res.body) {
    const isJson = res.headers.get("content-type")?.includes("application/json");
    const body = isJson ? await res.json().catch(() => null) : null;
    const message =
      (body && (body.message || body.error_code || body.detail)) ||
      `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventCount = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const chunk of events) {
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
      if (dataLine) {
        eventCount += 1;
        onLine(dataLine.slice("data: ".length));
      }
    }
  }
  // A final event with no trailing blank-line separator would otherwise be
  // silently dropped once the stream closes.
  if (buffer.startsWith("data: ")) {
    eventCount += 1;
    onLine(buffer.slice("data: ".length));
  }

  // A 200 response that closes having sent zero events means something
  // failed server-side after the response had already started (so it could
  // no longer become a normal error status) - this used to be a completely
  // silent failure (promise just resolves, caller thinks nothing happened).
  // Surface it so it isn't invisible if it ever happens again.
  if (eventCount === 0) {
    console.error(`SSE stream from ${url} closed with zero events - likely a server-side error after the response started.`);
    throw new ApiError("The server closed the connection unexpectedly without sending any progress.", 500);
  }
}

// ---------------------------------------------------------------------------
// Legacy /api/* surface (not used by the app UI - kept for reference/tooling)
// ---------------------------------------------------------------------------

export const legacyApi = {
  health: () => request<{ status: string; database: string; api: string }>("/api/health"),

  getGraph: () => request<GraphData>("/api/graph"),

  resetGraph: () => request<UploadResponseLegacy>("/api/reset", { method: "POST" }),

  uploadGraph: (payload: GraphData) =>
    request<UploadResponseLegacy>("/api/upload", {
      method: "POST",
      body: JSON.stringify({ json_payload: payload }),
    }),

  uploadFiles: (nodesFile?: File, edgesFile?: File) => {
    const form = new FormData();
    if (nodesFile) form.append("nodes_file", nodesFile);
    if (edgesFile) form.append("edges_file", edgesFile);
    return request<UploadResponseLegacy>("/api/upload", { method: "POST", body: form });
  },

  simulate: (payload: SimulationRequest) =>
    request<SimulationResponse>("/api/simulate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  plan: () => request<PlanningResponse>("/api/plan", { method: "POST" }),

  chat: (messages: ChatMessage[]) =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),
};

// ---------------------------------------------------------------------------
// /api/v1/* surface
// ---------------------------------------------------------------------------

export const v1Api = {
  // --- Auth (Phase 1) ---
  register: (payload: RegisterRequest) =>
    requestEnvelope<AuthResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  login: (payload: LoginRequest) =>
    requestEnvelope<AuthResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  me: () => requestEnvelope<CurrentUserResponse>("/api/v1/auth/me"),

  logout: () => requestEnvelope<null>("/api/v1/auth/logout", { method: "POST" }),

  // --- Dashboard / Assessments (Phase 2) ---
  dashboardSummary: () => requestEnvelope<DashboardSummary>("/api/v1/dashboard/summary"),

  listAssessments: () => requestEnvelope<Assessment[]>("/api/v1/assessments"),

  getAssessment: (id: string) => requestEnvelope<Assessment>(`/api/v1/assessments/${id}`),

  createAssessment: (payload: AssessmentCreateRequest) =>
    requestEnvelope<Assessment>("/api/v1/assessments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateAssessmentStatus: (id: string, status: AssessmentStatus) =>
    requestEnvelope<Assessment>(`/api/v1/assessments/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  // --- Document Upload (Phase 3: real file -> S3 -> RAG indexing) ---
  listUploads: (assessmentId: string) =>
    requestEnvelope<AssessmentUpload[]>(`/api/v1/assessments/${assessmentId}/uploads`),

  uploadDocument: (assessmentId: string, file: File, sourceType = "manual") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return requestEnvelope<AssessmentUpload>(`/api/v1/assessments/${assessmentId}/uploads`, {
      method: "POST",
      body: form,
    });
  },

  // Extracts a zip archive server-side and stores + indexes every supported
  // member as its own upload - see backend/app/api/v1/uploads.py's /uploads/zip.
  uploadZip: (assessmentId: string, file: File, sourceType = "manual") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return requestEnvelope<ZipUploadResponse>(`/api/v1/assessments/${assessmentId}/uploads/zip`, {
      method: "POST",
      body: form,
    });
  },

  // Same as uploadZip, streamed as Server-Sent Events so a UI can show live
  // per-file progress instead of one multi-minute blocking call - see
  // backend/app/services_v1/upload_service.py's upload_zip_archive_stream().
  streamUploadZip: (
    assessmentId: string,
    file: File,
    onEvent: (event: ZipStreamEvent) => void,
    sourceType = "manual",
    signal?: AbortSignal,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", sourceType);
    return streamSse(
      `/api/v1/assessments/${assessmentId}/uploads/zip/stream`,
      { method: "POST", body: form },
      (raw) => {
        try {
          onEvent(JSON.parse(raw) as ZipStreamEvent);
        } catch (err) {
          // A malformed/partial SSE line shouldn't crash the whole stream, but
          // silently dropping it previously left zero trace of a real problem
          // (e.g. a backend traceback embedded in what should've been a clean
          // JSON event) - log it so it's at least visible in devtools.
          console.error("Zip upload stream: failed to parse SSE event", raw, err);
        }
      },
      signal,
    );
  },

  // --- Document Discovery (streamed): reads every uploaded document, extracts
  // systems/dependencies from each, and auto-persists the resulting graph -
  // see backend/app/services_v1/discovery_service.py. `onEvent` fires once per
  // Server-Sent Event as it arrives; the promise resolves once the stream closes
  // (after the terminal "complete"/"error" event, not before). ---
  streamDiscovery: (assessmentId: string, onEvent: (event: DiscoveryEvent) => void, signal?: AbortSignal) =>
    streamSse(
      `/api/v1/assessments/${assessmentId}/discover/stream`,
      { method: "POST" },
      (raw) => {
        try {
          onEvent(JSON.parse(raw) as DiscoveryEvent);
        } catch (err) {
          console.error("Discovery stream: failed to parse SSE event", raw, err);
        }
      },
      signal,
    ),

  // Downloads the durably-stored nodes.csv/edges.csv from the most recent
  // discovery run for this assessment (see GET .../discover/{kind}.csv) -
  // independent of whether the SSE event that originally produced them is
  // still around client-side. text/csv, not envelope-wrapped.
  downloadDiscoveryCsv: async (assessmentId: string, kind: "nodes" | "edges"): Promise<string> => {
    const res = await fetch(`/api/v1/assessments/${assessmentId}/discover/${kind}.csv`, {
      credentials: "include",
    });
    if (!res.ok) {
      const isJson = res.headers.get("content-type")?.includes("application/json");
      const body = isJson ? await res.json().catch(() => null) : null;
      const message = (body && (body.message || body.detail)) || `Request failed with status ${res.status}`;
      throw new ApiError(message, res.status);
    }
    return res.text();
  },

  // --- Assessment Chat (document-grounded RAG, scoped to one assessment) ---
  assessmentChat: (assessmentId: string, messages: ChatMessage[]) =>
    requestEnvelope<AssessmentChatResponse>(`/api/v1/assessments/${assessmentId}/chat`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),

  // --- Assessment Graph Persistence ---
  persistGraph: (assessmentId: string, payload: GraphData) =>
    requestEnvelope<GraphPersistResponse>(`/api/v1/assessments/${assessmentId}/graph`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getAssessmentGraph: (assessmentId: string) =>
    requestEnvelope<AssessmentGraphResponse>(`/api/v1/assessments/${assessmentId}/graph`),

  // --- Simulation ---
  runSimulation: (assessmentId: string, payload: SimulateRequest) =>
    requestEnvelope<SimulationResultResponse>(`/api/v1/assessments/${assessmentId}/simulate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getSimulation: (assessmentId: string) =>
    requestEnvelope<SimulationResultResponse>(`/api/v1/assessments/${assessmentId}/simulate`),

  // --- Agent Runs (Phase 4/5/6/7: Discovery/Dependency/Planner/Risk + RAG + Bedrock) ---
  runPlanner: (assessmentId: string) =>
    requestEnvelope<RunPlannerResponse>(`/api/v1/assessments/${assessmentId}/agent-runs`, {
      method: "POST",
    }),

  // Streamed twin of runPlanner: `onEvent` fires once per Server-Sent Event as
  // it arrives (one per completed agent stage, then a terminal complete/error
  // event) - see backend/app/services_v1/agent_run_service.py's
  // run_planner_stream(). The promise resolves once the stream closes.
  streamPlanner: (assessmentId: string, onEvent: (event: PlannerStreamEvent) => void, signal?: AbortSignal) =>
    streamSse(
      `/api/v1/assessments/${assessmentId}/agent-runs/stream`,
      { method: "POST" },
      (raw) => {
        try {
          onEvent(JSON.parse(raw) as PlannerStreamEvent);
        } catch (err) {
          console.error("Planner stream: failed to parse SSE event", raw, err);
        }
      },
      signal,
    ),

  // Reconstructs the last completed planner run from persisted AgentRun rows
  // without re-running anything - null if the planner has never successfully
  // completed for this assessment.
  getLatestPlannerResult: (assessmentId: string) =>
    requestEnvelope<RunPlannerResponse | null>(`/api/v1/assessments/${assessmentId}/agent-runs/latest`),

  listAgentRuns: (assessmentId: string) =>
    requestEnvelope<AgentRunResponse[]>(`/api/v1/assessments/${assessmentId}/agent-runs`),

  // --- Migration Waves ---
  listWaves: (assessmentId: string) =>
    requestEnvelope<MigrationWave[]>(`/api/v1/assessments/${assessmentId}/waves`),

  createWaves: (assessmentId: string, waves: WaveItem[]) =>
    requestEnvelope<MigrationWave[]>(`/api/v1/assessments/${assessmentId}/waves`, {
      method: "POST",
      body: JSON.stringify({ waves }),
    }),

  // --- Report / Feedback / Final Migration Plan (Phase 7/8/9) ---
  generateReport: (assessmentId: string) =>
    requestEnvelope<ReportResponse>(`/api/v1/assessments/${assessmentId}/report`, {
      method: "POST",
    }),

  getReport: (assessmentId: string) =>
    requestEnvelope<ReportResponse>(`/api/v1/assessments/${assessmentId}/report`),

  submitReportFeedback: (assessmentId: string, payload: ReportFeedbackRequest) =>
    requestEnvelope<ReportResponse>(`/api/v1/assessments/${assessmentId}/report/feedback`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  generateMigrationPlan: (assessmentId: string) =>
    requestEnvelope<ReportResponse>(`/api/v1/assessments/${assessmentId}/migration-plan`, {
      method: "POST",
    }),

  // --- Report feedback loop (revise + version history) + PDF export ---
  reviseReport: (assessmentId: string, payload: ReportReviseRequest) =>
    requestEnvelope<ReviseReportResponse>(`/api/v1/assessments/${assessmentId}/report/revise`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getReportHistory: (assessmentId: string) =>
    requestEnvelope<ReportRevisionSummary[]>(`/api/v1/assessments/${assessmentId}/report/history`),

  getReportRevision: (assessmentId: string, version: number) =>
    requestEnvelope<ReportRevisionDetail>(`/api/v1/assessments/${assessmentId}/report/history/${version}`),

  getReportPdf: async (assessmentId: string): Promise<Blob> => {
    const res = await fetch(`/api/v1/assessments/${assessmentId}/report/pdf`, {
      credentials: "include",
    });
    if (!res.ok) {
      const isJson = res.headers.get("content-type")?.includes("application/json");
      const body = isJson ? await res.json().catch(() => null) : null;
      const message = (body && (body.message || body.detail)) || `Request failed with status ${res.status}`;
      throw new ApiError(message, res.status);
    }
    return res.blob();
  },

  getMigrationPlanPdf: async (assessmentId: string): Promise<Blob> => {
    const res = await fetch(`/api/v1/assessments/${assessmentId}/migration-plan/pdf`, {
      credentials: "include",
    });
    if (!res.ok) {
      const isJson = res.headers.get("content-type")?.includes("application/json");
      const body = isJson ? await res.json().catch(() => null) : null;
      const message = (body && (body.message || body.detail)) || `Request failed with status ${res.status}`;
      throw new ApiError(message, res.status);
    }
    return res.blob();
  },
};
