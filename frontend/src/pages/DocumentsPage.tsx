import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowRight, CheckCircle2, Download, Loader2, Sparkles, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/Card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InfoBanner } from "@/components/InfoBanner";
import { ApiError, v1Api } from "@/lib/api";
import { describeDiscoveryEvent } from "@/lib/discovery-events";
import { useDiscoveryRun } from "@/lib/discovery-run-context";
import { downloadTextFile } from "@/lib/download-file";
import { useRefetchOnRunComplete } from "@/lib/use-refetch-on-run-complete";
import type { AssessmentUpload, DiscoveryCompleteEvent, DiscoveryCsvGeneratedEvent } from "@/types/api";

const STATUS_VARIANT: Record<string, "neutral" | "amber" | "emerald" | "rose"> = {
  processed: "emerald",
  processing: "amber",
  failed: "rose",
  uploaded: "neutral",
};

const UPLOAD_ACCEPT = ".pdf,.docx,.pptx,.xlsx,.csv,.json,.txt,.md,.zip";

function isZipFile(file: File): boolean {
  return (
    file.type === "application/zip" ||
    file.type === "application/x-zip-compressed" ||
    file.name.toLowerCase().endsWith(".zip")
  );
}

/** Phase 3: React Web UI -> FastAPI -> Amazon S3 (store) -> Document Processing
 * Service (extract -> chunk -> embed) -> Qdrant + PostgreSQL, then explicit
 * Document Discovery (extract systems/dependencies -> nodes.csv/edges.csv ->
 * auto-persisted digital twin graph). The discovery run itself lives in
 * DiscoveryRunProvider (app root, see App.tsx) rather than this component's
 * own state - it's a background operation, so it needs to survive the user
 * navigating away and back, same as PlannerRunProvider does for planner runs.
 * This page just starts it and renders whatever the shared context reports
 * for *this* assessment; see DiscoveryRunPanel for the cross-page version. */
export function DocumentsPage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;
  const [uploads, setUploads] = useState<AssessmentUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const discoveryRun = useDiscoveryRun();
  const isLiveHere = discoveryRun.assessmentId === assessmentId && discoveryRun.status !== "idle";
  const processing = isLiveHere && discoveryRun.status === "running";
  const events = isLiveHere ? discoveryRun.events : [];
  const processError = isLiveHere && discoveryRun.status === "error" ? discoveryRun.errorMessage : null;

  const finalEvent = events.find((e): e is DiscoveryCompleteEvent => e.type === "complete");
  const csvEvent = events.find((e): e is DiscoveryCsvGeneratedEvent => e.type === "csv_generated");

  // This page's component instance is reused across different assessments -
  // without this guard, switching from assessment A to B while A's slower
  // listUploads() is still in flight lets A's response land after B's and
  // overwrite B's uploads table with A's files.
  const assessmentIdRef = useRef(assessmentId);
  assessmentIdRef.current = assessmentId;

  async function refresh() {
    const forId = assessmentId;
    const result = await v1Api.listUploads(forId);
    if (assessmentIdRef.current === forId) setUploads(result);
  }

  useEffect(() => {
    refresh().catch(() => setError("Could not load uploads."));
  }, [assessmentId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events]);

  // Once a discovery run for this assessment completes, the uploads list's
  // per-file RAG-indexing status (separate from discovery) is unaffected, but
  // re-fetching keeps everything visibly in sync in one place.
  useRefetchOnRunComplete(discoveryRun.status, discoveryRun.assessmentId, assessmentId, () => {
    refresh().catch(() => undefined);
  });

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      if (isZipFile(file)) {
        const zipResult = await v1Api.uploadZip(assessmentId, file);
        await refresh();
        toast.success(
          `${zipResult.extracted_count} document${zipResult.extracted_count === 1 ? "" : "s"} extracted from ${file.name} and queued for indexing.`,
        );
        if (zipResult.skipped.length > 0) {
          toast(
            `${zipResult.skipped.length} file${zipResult.skipped.length === 1 ? "" : "s"} in ${file.name} were skipped (unsupported type or too large).`,
          );
        }
      } else {
        await v1Api.uploadDocument(assessmentId, file);
        await refresh();
        toast.success(`${file.name} uploaded and queued for indexing.`);
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Upload failed.";
      setError(message);
      toast.error(message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  return (
    <div className="space-y-6">
      <InfoBanner id="documents" title="What happens to what I upload here?">
        <p>
          Each document is stored and indexed for the Executive Copilot to search, and "Process Documents"
          below reads all of them together to extract systems and their dependencies, building the Digital
          Twin Graph automatically - nothing here is manual. Upload individually, or bundle several files into
          one .zip; it's extracted server-side and every supported file inside is handled the same way. Feel
          free to navigate away once processing starts - you'll get a notification when it's done.
        </p>
      </InfoBanner>

      <label className="block cursor-pointer">
        <Card className="flex flex-col items-center gap-2 border-dashed p-10 text-center transition hover:border-primary/30">
          <input
            type="file"
            accept={UPLOAD_ACCEPT}
            className="hidden"
            onChange={handleFileChange}
            disabled={uploading}
          />
          <UploadCloud className="h-6 w-6 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {uploading ? "Uploading and indexing..." : "Click to choose a file, or a .zip archive of several files"}
          </span>
        </Card>
      </label>
      <p className="-mt-3 text-xs text-muted-foreground">
        Supported: PDF, Word, PowerPoint, Excel, CSV, JSON, TXT, Markdown, or a .zip of several files. Best
        results come from <strong className="text-foreground/80">structured exports</strong> - a database schema
        dump, an OpenAPI/Swagger spec, a stored-procedure export, or a system/application inventory (CSV/XLSX).
        Free-text documents (BRDs, HLDs, design notes) are read by AI and still useful, just inherently less
        precise than a structured export.
      </p>

      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="space-y-2">
        {uploads.map((u) => (
          <Card key={u.upload_id} className="flex items-center justify-between px-4 py-3 text-sm">
            <div>
              <p className="font-medium text-foreground">{u.filename}</p>
              <p className="text-muted-foreground">
                {u.source_type} - {u.chunk_count} chunk{u.chunk_count === 1 ? "" : "s"} indexed
              </p>
            </div>
            <Badge variant={STATUS_VARIANT[u.status] ?? "neutral"}>{u.status}</Badge>
          </Card>
        ))}
        {uploads.length === 0 && <p className="text-sm text-muted-foreground">No documents uploaded yet.</p>}
      </div>

      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Process Documents</h3>
            <p className="text-sm text-muted-foreground">
              Analyzes every uploaded document, extracts systems and dependencies, and builds
              the digital twin graph. Re-run any time after adding more documents.
            </p>
          </div>
          <Button onClick={() => discoveryRun.startRun(assessmentId)} disabled={uploads.length === 0 || processing}>
            {processing ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Processing...
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" /> Process Documents
              </>
            )}
          </Button>
        </div>

        {events.length > 0 && (
          <div
            ref={logRef}
            className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-border bg-black/20 p-3 font-mono text-xs text-muted-foreground"
          >
            {events.map((event, i) => (
              <p
                key={i}
                className={
                  event.type === "error"
                    ? "text-destructive"
                    : event.type === "complete"
                      ? "font-semibold text-foreground"
                      : undefined
                }
              >
                {describeDiscoveryEvent(event)}
              </p>
            ))}
          </div>
        )}

        {processError && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{processError}</span>
          </div>
        )}

        {finalEvent && finalEvent.status === "graph_updated" && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm">
            <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-300">
              <CheckCircle2 className="h-4 w-4" />
              <span>
                {finalEvent.node_count} systems, {finalEvent.edge_count} dependencies persisted.
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {csvEvent && (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => downloadTextFile("nodes.csv", csvEvent.nodes_csv)}
                  >
                    <Download className="h-3.5 w-3.5" /> nodes.csv
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => downloadTextFile("edges.csv", csvEvent.edges_csv)}
                  >
                    <Download className="h-3.5 w-3.5" /> edges.csv
                  </Button>
                </>
              )}
              <Button asChild size="sm">
                <Link to={`/assessments/${assessmentId}/graph`}>
                  View Digital Twin <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
