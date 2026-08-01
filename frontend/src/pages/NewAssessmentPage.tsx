import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Archive,
  ChevronDown,
  ChevronUp,
  File as FileIcon,
  FileSpreadsheet,
  FileText,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/Card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ExtractionProgressModal, type ExtractionStep } from "@/components/ExtractionProgressModal";
import { InfoBanner } from "@/components/InfoBanner";
import { ApiError, v1Api } from "@/lib/api";
import { discoveryEventsToProgress } from "@/lib/discovery-events";
import { useDiscoveryRun } from "@/lib/discovery-run-context";
import type { AssessmentUpload } from "@/types/api";

const CLOUD_OPTIONS = ["AWS", "Azure", "GCP"];
const TEXT_PREVIEW_EXTENSIONS = [".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml"];
const PREVIEW_CHAR_LIMIT = 8000;
const UPLOAD_ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.json,.txt,.md,.zip";

/** Metadata for one row in the document list. `sourceFile` is only present
 * when the browser actually holds the bytes (a staged file, or a directly-
 * uploaded single file) - that's what makes inline preview possible. Zip
 * archive members are extracted server-side, so their rows carry only the
 * metadata the upload response returned. */
interface DisplayFile {
  name: string;
  size: number | null;
  contentType: string;
  sourceFile?: File;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isZipFile(file: File): boolean {
  return (
    file.type === "application/zip" ||
    file.type === "application/x-zip-compressed" ||
    file.name.toLowerCase().endsWith(".zip")
  );
}

function isPdf(name: string, contentType: string): boolean {
  return contentType === "application/pdf" || name.toLowerCase().endsWith(".pdf");
}

function isTextPreviewable(name: string, contentType: string): boolean {
  if (contentType.startsWith("text/") || contentType === "application/json") return true;
  const lower = name.toLowerCase();
  return TEXT_PREVIEW_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function iconForFile(name: string) {
  const lower = name.toLowerCase();
  if (lower.endsWith(".csv") || lower.endsWith(".xlsx") || lower.endsWith(".json")) return FileSpreadsheet;
  if (lower.endsWith(".pdf") || lower.endsWith(".docx") || lower.endsWith(".txt") || lower.endsWith(".md")) {
    return FileText;
  }
  if (lower.endsWith(".zip")) return Archive;
  return FileIcon;
}

const STATUS_STYLES: Record<string, string> = {
  processing: "bg-amber-500/15 text-amber-300",
  processed: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-rose-500/15 text-rose-300",
};

function StatusBadge({ status, chunkCount }: { status: string; chunkCount?: number }) {
  return (
    <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.processing}`}>
      {status === "processed" ? `${chunkCount ?? 0} chunk${chunkCount === 1 ? "" : "s"}` : status}
    </span>
  );
}

interface FileRowProps {
  display: DisplayFile;
  isExpanded: boolean;
  onToggle: () => void;
  onRemove?: () => void;
  status?: string;
  chunkCount?: number;
  previewLoading: boolean;
  previewText: string | null;
  previewUrl: string | null;
}

function FileRow({
  display,
  isExpanded,
  onToggle,
  onRemove,
  status,
  chunkCount,
  previewLoading,
  previewText,
  previewUrl,
}: FileRowProps) {
  const Icon = iconForFile(display.name);
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-muted/30">
      <div className="flex items-center gap-3 p-2.5">
        <Icon className="h-4 w-4 shrink-0 text-primary" />
        <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-foreground">{display.name}</p>
            <p className="text-xs text-muted-foreground">
              {display.size !== null ? `${formatFileSize(display.size)} · ` : "extracted from archive · "}
              {display.contentType || "unknown type"}
            </p>
          </div>
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
        </button>
        {status && <StatusBadge status={status} chunkCount={chunkCount} />}
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="shrink-0 text-muted-foreground transition hover:text-destructive"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {isExpanded && (
        <div className="border-t border-border p-3">
          {previewLoading ? (
            <p className="text-xs text-muted-foreground">Loading preview...</p>
          ) : previewUrl ? (
            <iframe src={previewUrl} className="h-80 w-full rounded-md bg-white" title={`Preview of ${display.name}`} />
          ) : previewText !== null ? (
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-input/40 p-3 text-xs text-foreground/80">
              {previewText}
            </pre>
          ) : (
            <p className="text-xs text-muted-foreground">No inline preview available for this file type - metadata only.</p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Phase 2 + start of Phase 3. Files can't be uploaded before the assessment
 * exists, so the flow is: stage files (preview/remove freely) -> "Upload
 * documents" creates the assessment and actually processes+stores each file
 * -> once nothing's left pending, "Start assessment" (right panel) navigates
 * into the assessment's dashboard.
 */
export function NewAssessmentPage() {
  const navigate = useNavigate();
  const [customerName, setCustomerName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [targetCloud, setTargetCloud] = useState(CLOUD_OPTIONS[0]);

  const [assessmentId, setAssessmentId] = useState<string | null>(null);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<{ display: DisplayFile; result: AssessmentUpload }[]>([]);

  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [uploadSteps, setUploadSteps] = useState<ExtractionStep[]>([]);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Document Discovery runs in the shared DiscoveryRunProvider (app root), not
  // local state - it's a background operation and needs to survive navigating
  // away from this page entirely (see DocumentsPage for the same pattern).
  // Progress here is purely derived from whatever the context reports for the
  // assessment this page just created.
  const discoveryRun = useDiscoveryRun();
  const discoveryLiveHere = assessmentId !== null && discoveryRun.assessmentId === assessmentId && discoveryRun.status !== "idle";
  const { steps: discoverySteps, percent: discoveryPercent } = discoveryLiveHere
    ? discoveryEventsToProgress(discoveryRun.events)
    : { steps: [], percent: 0 };

  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  // togglePreview's `await file.text()` can resolve after the user has since
  // collapsed this file and expanded a different one - without checking this
  // ref (kept current every render, unlike the closed-over `key` param) the
  // late resolution would overwrite previewText/previewLoading for whichever
  // file happens to be expanded *now*, mislabeled as that file's own preview.
  const expandedKeyRef = useRef(expandedKey);
  expandedKeyRef.current = expandedKey;

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const detailsLocked = assessmentId !== null;
  const canSubmit = customerName.trim() !== "" && projectName.trim() !== "";
  const hasPendingUploads = stagedFiles.length > 0;
  // The assessment is useless without at least one document to build the
  // digital twin graph from - "Start assessment" stays disabled until one
  // has actually finished uploading (not just staged).
  const canStart = canSubmit && uploadedFiles.length > 0;

  function handleFilesSelected(e: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []);
    setStagedFiles((prev) => [...prev, ...selected]);
    e.target.value = "";
  }

  function removeStagedFile(index: number) {
    setStagedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  async function togglePreview(key: string, display: DisplayFile) {
    if (expandedKey === key) {
      setExpandedKey(null);
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setPreviewText(null);
    setExpandedKey(key);

    // Zip archive members are extracted server-side - the browser never holds
    // their bytes, so there's nothing to preview (falls through to the "no
    // inline preview" message).
    const file = display.sourceFile;
    if (!file) return;

    if (isPdf(file.name, file.type)) {
      setPreviewUrl(URL.createObjectURL(file));
      return;
    }
    if (isTextPreviewable(file.name, file.type)) {
      setPreviewLoading(true);
      try {
        const text = await file.text();
        if (expandedKeyRef.current !== key) return;
        setPreviewText(text.length > PREVIEW_CHAR_LIMIT ? `${text.slice(0, PREVIEW_CHAR_LIMIT)}\n\n... (truncated)` : text);
      } finally {
        if (expandedKeyRef.current === key) setPreviewLoading(false);
      }
    }
  }

  async function ensureAssessmentCreated(): Promise<string> {
    if (assessmentId) return assessmentId;
    const assessment = await v1Api.createAssessment({
      customer_name: customerName,
      project_name: projectName,
      target_cloud: targetCloud,
    });
    setAssessmentId(assessment.assessment_id);
    return assessment.assessment_id;
  }

  async function handleUpload() {
    setError(null);
    setUploading(true);
    const toUpload = [...stagedFiles];
    setUploadPercent(0);
    setUploadSteps(
      toUpload.map((file, i) => ({
        id: `${i}-${file.name}`,
        label: file.name,
        detail: formatFileSize(file.size),
        status: "pending" as const,
      })),
    );

    try {
      const id = await ensureAssessmentCreated();
      let documentsAdded = 0;
      let totalSkipped = 0;

      for (let i = 0; i < toUpload.length; i++) {
        const file = toUpload[i];
        const stepId = `${i}-${file.name}`;
        setUploadSteps((prev) =>
          prev.map((s) => (s.id === stepId ? { ...s, status: "active", detail: isZipFile(file) ? "Extracting archive..." : "Uploading..." } : s)),
        );

        if (isZipFile(file)) {
          let zipExtracted = 0;
          let zipSkipped = 0;

          await v1Api.streamUploadZip(id, file, (event) => {
            if (event.type === "member_start") {
              setUploadSteps((prev) => [
                ...prev,
                {
                  id: `${stepId}-m-${event.index}`,
                  label: event.filename,
                  detail: `Analyzing (${event.index}/${event.total})...`,
                  status: "active",
                },
              ]);
              setUploadPercent(Math.round(((i + (event.index - 1) / event.total) / toUpload.length) * 100));
            } else if (event.type === "member_result") {
              setUploadSteps((prev) =>
                prev.map((s) =>
                  s.id === `${stepId}-m-${event.index}`
                    ? {
                        ...s,
                        status: event.status === "failed" ? ("error" as const) : ("done" as const),
                        detail: event.status === "failed" ? "Indexing failed" : `${event.chunk_count} chunk${event.chunk_count === 1 ? "" : "s"}`,
                      }
                    : s,
                ),
              );
              setUploadPercent(Math.round(((i + event.index / event.total) / toUpload.length) * 100));
            } else if (event.type === "member_skipped") {
              setUploadSteps((prev) => [
                ...prev,
                { id: `${stepId}-m-${event.index}`, label: event.filename, detail: `Skipped - ${event.reason}`, status: "done" },
              ]);
            } else if (event.type === "complete") {
              zipExtracted = event.extracted_count;
              zipSkipped = event.skipped_count;
              setUploadedFiles((prev) => [
                ...prev,
                ...event.uploads.map((result) => ({
                  display: { name: result.filename, size: null, contentType: result.content_type },
                  result,
                })),
              ]);
              setUploadSteps((prev) =>
                prev.map((s) =>
                  s.id === stepId
                    ? {
                        ...s,
                        status: "done" as const,
                        detail: `${event.extracted_count} document${event.extracted_count === 1 ? "" : "s"} extracted${
                          event.skipped_count ? `, ${event.skipped_count} skipped` : ""
                        }`,
                      }
                    : s,
                ),
              );
            } else if (event.type === "error") {
              setUploadSteps((prev) => prev.map((s) => (s.id === stepId ? { ...s, status: "error" as const, detail: event.message } : s)));
              throw new ApiError(event.message, 500);
            }
          });

          documentsAdded += zipExtracted;
          totalSkipped += zipSkipped;
        } else {
          const result = await v1Api.uploadDocument(id, file);
          setUploadedFiles((prev) => [
            ...prev,
            { display: { name: file.name, size: file.size, contentType: file.type, sourceFile: file }, result },
          ]);
          documentsAdded += 1;
          setUploadSteps((prev) =>
            prev.map((s) => (s.id === stepId ? { ...s, status: "done" as const, detail: formatFileSize(file.size) } : s)),
          );
        }
        setStagedFiles((prev) => prev.filter((f) => f !== file));
        setUploadPercent(Math.round(((i + 1) / toUpload.length) * 100));
      }

      toast.success(`${documentsAdded} document${documentsAdded === 1 ? "" : "s"} uploaded and queued for indexing.`);
      if (totalSkipped > 0) {
        toast(`${totalSkipped} file${totalSkipped === 1 ? "" : "s"} in uploaded archives were skipped (unsupported type or too large).`);
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Upload failed.";
      setError(message);
      toast.error(message);
      setUploadSteps((prev) => prev.map((s) => (s.status === "active" ? { ...s, status: "error" as const, detail: message } : s)));
    } finally {
      setUploading(false);
    }
  }

  async function handleStart() {
    setError(null);
    setStarting(true);
    try {
      const id = await ensureAssessmentCreated();

      // Nothing uploaded -> nothing to extract a graph from; go straight to
      // the dashboard (planner auto-start needs a graph to run on). Otherwise
      // kick off discovery in the shared background context - the effect
      // below navigates once it settles (see DiscoveryRunProvider for the
      // toasts/notifications, which fire regardless of whether we're still on
      // this page by then).
      if (uploadedFiles.length > 0) {
        discoveryRun.startRun(id);
      } else {
        navigate(`/assessments/${id}`);
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not start the assessment.";
      setError(message);
      toast.error(message);
      setStarting(false);
    }
  }

  // Navigates on once the background discovery run (started above) settles -
  // separate from handleStart's own try/catch because startRun() doesn't
  // return a promise to await (it's fire-and-forget by design, see
  // DiscoveryRunProvider), and because this needs to keep working even if the
  // user has already navigated away and DiscoveryRunProvider's own toast is
  // what actually informs them, not this effect.
  useEffect(() => {
    if (!starting || !assessmentId) return;
    if (discoveryRun.assessmentId !== assessmentId) return;
    if (discoveryRun.status === "complete") {
      const graphBuilt = discoveryRun.events.some((e) => e.type === "complete" && e.status === "graph_updated");
      navigate(`/assessments/${assessmentId}`, graphBuilt ? { state: { autoStartPlanner: true } } : undefined);
    } else if (discoveryRun.status === "error") {
      navigate(`/assessments/${assessmentId}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [starting, assessmentId, discoveryRun.status, discoveryRun.assessmentId]);

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-3 text-2xl font-semibold text-foreground">New migration assessment</h1>

      <div className="mb-6">
        <InfoBanner id="new-assessment" title="What is a migration assessment?">
          <p>
            An assessment is the container for everything EMIOS builds around one customer's cloud migration: a
            digital twin of their systems and dependencies, cascading-failure and cost simulations, an AI-negotiated
            wave sequencing plan, and an executive-ready report. Give it a name and target cloud, attach whatever
            architecture documentation you have, and the rest of the tabs on the left build on top of it
            automatically.
          </p>
        </InfoBanner>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Left: details + file picker */}
        <Card className="space-y-4 p-6 lg:col-span-3">
          <fieldset disabled={detailsLocked} className="space-y-4 disabled:opacity-60">
            <div className="space-y-1.5">
              <Label htmlFor="customer">Customer name</Label>
              <Input
                id="customer"
                required
                value={customerName}
                onChange={(e) => setCustomerName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="project">Project name</Label>
              <Input
                id="project"
                required
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cloud">Target cloud</Label>
              <Select value={targetCloud} onValueChange={setTargetCloud} disabled={detailsLocked}>
                <SelectTrigger id="cloud" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CLOUD_OPTIONS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </fieldset>
          {detailsLocked && (
            <p className="text-xs text-muted-foreground">
              Assessment created - these details are now locked. Add more documents below any time.
            </p>
          )}

          <div>
            <label className="mb-1 block text-sm text-foreground/80">
              Company documents <span className="text-destructive dark:text-[#FF204E]">(required)</span>
            </label>
            <label className="block cursor-pointer">
              <input
                type="file"
                multiple
                accept={UPLOAD_ACCEPT}
                className="hidden"
                onChange={handleFilesSelected}
                disabled={uploading}
              />
              <div className="flex flex-col items-center gap-2 rounded-lg border-2 border-dashed border-border p-6 text-center transition hover:border-primary/30">
                <UploadCloud className="h-5 w-5 text-muted-foreground" />
                <span className="text-sm text-muted-foreground">
                  Click to attach architecture notes, runbooks, CSV/JSON exports, or a .zip archive of several
                  documents
                </span>
              </div>
            </label>
            <p className="mt-2 text-xs text-muted-foreground">
              Supported: PDF, Word, PowerPoint, Excel, CSV, JSON, TXT, Markdown, or a single .zip of several files.
              Best results come from <strong className="text-foreground/80">structured exports</strong> - a database
              schema dump, an OpenAPI/Swagger spec, a stored-procedure export, or a system/application inventory
              (CSV/XLSX) - these parse deterministically. Free-text docs (BRDs, HLDs, design notes) are still useful
              and get read by AI, but are inherently less precise than a structured export.
            </p>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </Card>

        {/* Right: review + files + primary actions */}
        <Card className="p-6 lg:col-span-2">
          <h2 className="mb-4 text-sm font-semibold text-foreground">Review</h2>
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Customer</dt>
              <dd className="truncate text-foreground">{customerName || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Project</dt>
              <dd className="truncate text-foreground">{projectName || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">Target cloud</dt>
              <dd className="text-foreground">{targetCloud}</dd>
            </div>
          </dl>

          <div className="mt-5 border-t border-border pt-4">
            <p className="mb-3 text-xs uppercase tracking-wide text-muted-foreground">
              Documents ({stagedFiles.length + uploadedFiles.length})
            </p>

            {stagedFiles.length === 0 && uploadedFiles.length === 0 ? (
              <p className="text-sm text-muted-foreground">No files attached yet - at least one is required.</p>
            ) : (
              <div className="max-h-[min(420px,50vh)] space-y-2 overflow-y-auto pr-1">
                {uploadedFiles.map(({ display, result }) => {
                  const key = `uploaded-${result.upload_id}`;
                  return (
                    <FileRow
                      key={key}
                      display={display}
                      isExpanded={expandedKey === key}
                      onToggle={() => togglePreview(key, display)}
                      status={result.status}
                      chunkCount={result.chunk_count}
                      previewLoading={expandedKey === key && previewLoading}
                      previewText={expandedKey === key ? previewText : null}
                      previewUrl={expandedKey === key ? previewUrl : null}
                    />
                  );
                })}
                {stagedFiles.map((file, i) => {
                  const key = `staged-${i}-${file.name}`;
                  const display: DisplayFile = {
                    name: file.name,
                    size: file.size,
                    contentType: file.type,
                    sourceFile: file,
                  };
                  return (
                    <FileRow
                      key={key}
                      display={display}
                      isExpanded={expandedKey === key}
                      onToggle={() => togglePreview(key, display)}
                      onRemove={uploading ? undefined : () => removeStagedFile(i)}
                      previewLoading={expandedKey === key && previewLoading}
                      previewText={expandedKey === key ? previewText : null}
                      previewUrl={expandedKey === key ? previewUrl : null}
                    />
                  );
                })}
              </div>
            )}
          </div>

          <div className="mt-6 border-t border-border pt-4">
            {hasPendingUploads ? (
              <Button onClick={handleUpload} disabled={!canSubmit || uploading} className="w-full">
                <UploadCloud className="h-4 w-4 shrink-0" />
                <span className="min-w-0 truncate">
                  {uploading ? "Uploading..." : `Upload ${stagedFiles.length} document${stagedFiles.length === 1 ? "" : "s"}`}
                </span>
              </Button>
            ) : (
              <>
                <Button onClick={handleStart} disabled={!canStart || starting} className="w-full">
                  <Sparkles className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 truncate">{starting ? "Extracting..." : "Start assessment"}</span>
                </Button>
                {canSubmit && uploadedFiles.length === 0 && (
                  <p className="mt-2 text-center text-xs text-destructive dark:text-[#FF204E]">
                    Attach and upload at least one document above - without one there's nothing to build a digital
                    twin graph from.
                  </p>
                )}
              </>
            )}
          </div>
        </Card>
      </div>

      <ExtractionProgressModal
        open={uploading}
        title="Uploading documents"
        subtitle="Staging files and extracting any archives."
        percent={uploadPercent}
        steps={uploadSteps}
      />
      <ExtractionProgressModal
        open={starting && discoverySteps.length > 0}
        title="Extracting systems & dependencies"
        subtitle="Building the digital twin graph from your documents."
        percent={discoveryPercent}
        steps={discoverySteps}
      />
    </div>
  );
}
