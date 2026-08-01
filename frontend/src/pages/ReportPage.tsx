import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { Card } from "@/components/Card";
import { InfoBanner } from "@/components/InfoBanner";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { ApiError, v1Api } from "@/lib/api";
import { useReportRun } from "@/lib/report-run-context";
import type { ReportResponse, ReportRevisionDetail, ReportRevisionSummary, ReportSection } from "@/types/api";

const SECTION_LABELS: Record<ReportSection, string> = {
  executive_summary: "Executive summary",
  risk_summary: "Risk summary",
  migration_waves: "Migration waves",
  recommendations: "Recommendations",
};

function formatChangedSections(sections: ReportSection[]): string {
  return sections.map((s) => SECTION_LABELS[s] ?? s).join(", ");
}

/** Phase 7 (display), Phase 8 (simplified feedback - thumbs up/down + comment,
 * no reviewer role/approval gate), Phase 9 (final migration plan), plus the
 * feedback-loop revision + version history and PDF export added on top. */
export function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const assessmentId = id as string;
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [feedbackText, setFeedbackText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [lastChangedSections, setLastChangedSections] = useState<ReportSection[]>([]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<ReportRevisionSummary[] | null>(null);
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);
  const [versionDetails, setVersionDetails] = useState<Record<number, ReportRevisionDetail>>({});

  // Report generation itself now runs in the background via ReportRunProvider
  // (app root, see App.tsx) - auto-started the moment the multi-agent planner
  // finishes (chained from PlannerRunProvider), the same way the planner
  // auto-starts once Document Discovery builds a graph. By the time a user
  // gets to this tab, generation has often already completed elsewhere; this
  // page just reflects whichever run (if any) belongs to this assessment.
  const reportRun = useReportRun();
  const isLiveHere = reportRun.assessmentId === assessmentId && reportRun.status !== "idle";
  const generating = isLiveHere && reportRun.status === "running";

  useEffect(() => {
    v1Api
      .getReport(assessmentId)
      .then(setReport)
      .catch(() => setReport(null));
  }, [assessmentId]);

  // Pick up whatever the live run (if any) produces for this assessment -
  // covers both the auto-started run finishing while the user is already
  // here, and a manual "Try again"/"Regenerate report" click below.
  useEffect(() => {
    if (isLiveHere && reportRun.status === "complete" && reportRun.result) {
      setReport(reportRun.result);
      setLastChangedSections([]);
      setHistory(null);
    }
    if (isLiveHere && reportRun.status === "error") {
      setError(reportRun.errorMessage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLiveHere, reportRun.status, reportRun.result, reportRun.errorMessage]);

  function handleGenerateReport() {
    setError(null);
    reportRun.startRun(assessmentId);
  }

  /** Quick positive signal - just records the rating (+ optional comment), no revision. */
  async function handleLooksGood() {
    setError(null);
    setBusy("feedback");
    try {
      const result = await v1Api.submitReportFeedback(assessmentId, {
        rating: "up",
        comment: feedbackText.trim() || undefined,
      });
      setReport(result);
      setFeedbackText("");
      toast.success("Feedback recorded.");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not record feedback.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  /** "Needs changes" is the change request itself: records the down rating and, in the
   * same action, runs the AI revision pass on the report using that same feedback text. */
  async function handleRequestChanges() {
    const feedback = feedbackText.trim();
    if (!feedback) return;
    setError(null);
    setBusy("revise");
    try {
      await v1Api.submitReportFeedback(assessmentId, { rating: "down", comment: feedback });
      const result = await v1Api.reviseReport(assessmentId, { feedback });
      setReport(result);
      setLastChangedSections(result.changed_sections);
      setFeedbackText("");
      setHistory(null); // stale - refetch next time the history panel is opened
      toast.success(`Report updated: ${formatChangedSections(result.changed_sections)}.`);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not revise the report from that feedback.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  async function handleGeneratePlan() {
    setError(null);
    setBusy("plan");
    try {
      const result = await v1Api.generateMigrationPlan(assessmentId);
      setReport(result);
      toast.success("Final migration plan generated.");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not generate migration plan.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  async function handleDownloadPdf() {
    setError(null);
    setBusy("pdf");
    try {
      const blob = await v1Api.getReportPdf(assessmentId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `report_${assessmentId}_v${report?.current_version ?? 1}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not download the report PDF.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  async function handleDownloadPlanPdf() {
    setError(null);
    setBusy("plan-pdf");
    try {
      const blob = await v1Api.getMigrationPlanPdf(assessmentId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `migration_plan_${assessmentId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not download the migration plan PDF.";
      setError(message);
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  async function handleToggleHistory() {
    const opening = !historyOpen;
    setHistoryOpen(opening);
    if (opening && history === null) {
      setBusy("history");
      try {
        const result = await v1Api.getReportHistory(assessmentId);
        setHistory(result);
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "Could not load report history.";
        toast.error(message);
      } finally {
        setBusy(null);
      }
    }
  }

  async function handleViewVersion(version: number) {
    if (expandedVersion === version) {
      setExpandedVersion(null);
      return;
    }
    setExpandedVersion(version);
    if (versionDetails[version]) return;
    setBusy(`version-${version}`);
    try {
      const detail = await v1Api.getReportRevision(assessmentId, version);
      setVersionDetails((prev) => ({ ...prev, [version]: detail }));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : `Could not load version ${version}.`;
      toast.error(message);
    } finally {
      setBusy(null);
    }
  }

  const isChanged = (section: ReportSection) => lastChangedSections.includes(section);

  return (
    <div className="space-y-6">
      <InfoBanner id="report" title="What is the Report?">
        <p>
          An AI-generated executive summary of migration readiness - pulling together the 12-agent planner's
          complexity, risk, cloud readiness, and strategy simulation output into one shareable document,
          complete with a readiness score and concrete recommendations. Requires the multi-agent planner to
          have completed at least once, since the readiness score and risk summary are computed from its
          output. You can leave feedback to have specific sections revised, generate a final go/no-go
          migration strategy, and download either as a PDF.
        </p>
      </InfoBanner>

      {report && error && <p className="text-sm text-destructive">{error}</p>}

      {!report && (
        <Card className="p-10 text-center">
          {error ? (
            <>
              <p className="mb-3 text-sm text-destructive">{error}</p>
              <Button type="button" onClick={handleGenerateReport} disabled={generating}>
                {generating ? "Generating..." : "Try again"}
              </Button>
            </>
          ) : generating ? (
            <p className="text-sm text-muted-foreground">Generating your report...</p>
          ) : (
            <>
              <p className="mb-3 text-sm text-muted-foreground">
                No report yet - this normally starts on its own once the multi-agent planner finishes.
                If it's been a while, generate one now.
              </p>
              <Button type="button" onClick={handleGenerateReport}>
                Generate report
              </Button>
            </>
          )}
        </Card>
      )}

      {report && (
        <>
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-medium text-foreground">
              Report <span className="text-sm font-normal text-muted-foreground">v{report.current_version}</span>
            </h1>
            <Button type="button" variant="outline" onClick={handleDownloadPdf} disabled={busy === "pdf"}>
              {busy === "pdf" ? "Preparing PDF..." : "Download PDF"}
            </Button>
          </div>

          <Card className={cn("p-6", isChanged("executive_summary") && "ring-1 ring-emerald-500/40")}>
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="font-medium text-foreground">Executive summary</h2>
                {isChanged("executive_summary") && (
                  <Badge variant="secondary" className="text-emerald-300">
                    Updated
                  </Badge>
                )}
              </div>
              <Badge variant="secondary">Readiness {report.readiness_score}/100</Badge>
            </div>
            <Markdown text={report.executive_summary} />
            {!!report.recommendations?.length && (
              <>
                <div className="mt-4 flex items-center gap-2">
                  <h3 className="text-xs font-medium uppercase text-muted-foreground">Recommendations</h3>
                  {isChanged("recommendations") && (
                    <Badge variant="secondary" className="text-emerald-300">
                      Updated
                    </Badge>
                  )}
                </div>
                <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-muted-foreground">
                  {report.recommendations.map((rec, i) => (
                    <li key={i}>
                      <Markdown text={rec} className="inline text-inherit [&_p]:inline" />
                    </li>
                  ))}
                </ul>
              </>
            )}
            <Button
              type="button"
              variant="link"
              onClick={handleGenerateReport}
              disabled={generating}
              className="mt-4 h-auto p-0"
            >
              {generating ? "Regenerating..." : "Regenerate report"}
            </Button>
          </Card>

          <Card className="p-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-medium text-foreground">Final migration plan</h2>
              {report.final_migration_plan && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleDownloadPlanPdf}
                  disabled={busy === "plan-pdf"}
                >
                  {busy === "plan-pdf" ? "Preparing PDF..." : "Download plan PDF"}
                </Button>
              )}
            </div>
            {report.final_migration_plan ? (
              <Markdown text={report.final_migration_plan.strategy} />
            ) : (
              <p className="mb-3 text-sm text-muted-foreground">
                Not generated yet - this makes one final AI pass over the report (and any
                feedback below) to produce a go/no-go migration strategy.
              </p>
            )}
            <Button type="button" onClick={handleGeneratePlan} disabled={busy === "plan"} className="mt-3">
              {busy === "plan"
                ? "Generating..."
                : report.final_migration_plan
                  ? "Regenerate final plan"
                  : "Generate final migration plan"}
            </Button>
          </Card>

          <Card className="p-6">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-foreground">Version history</h2>
              <Button type="button" variant="link" onClick={handleToggleHistory} className="h-auto p-0">
                {historyOpen ? "Hide" : "Show"}
              </Button>
            </div>
            {historyOpen && (
              <div className="mt-3 space-y-2">
                {busy === "history" && <p className="text-sm text-muted-foreground">Loading...</p>}
                {history?.length === 0 && <p className="text-sm text-muted-foreground">No history yet.</p>}
                {history?.map((rev) => (
                  <div key={rev.version} className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between">
                      <div className="text-sm text-foreground">
                        v{rev.version} ·{" "}
                        <span className="text-muted-foreground">
                          {rev.source === "generate" ? "Regenerated" : "Revised from feedback"}
                        </span>{" "}
                        · <span className="text-muted-foreground">{new Date(rev.created_at).toLocaleString()}</span>
                      </div>
                      <Button
                        type="button"
                        variant="link"
                        onClick={() => handleViewVersion(rev.version)}
                        className="h-auto p-0"
                      >
                        {expandedVersion === rev.version ? "Hide" : "View"}
                      </Button>
                    </div>
                    {!!rev.changed_sections?.length && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Changed: {formatChangedSections(rev.changed_sections)}
                      </p>
                    )}
                    {rev.feedback_comment && (
                      <p className="mt-1 text-xs italic text-muted-foreground">"{rev.feedback_comment}"</p>
                    )}
                    {expandedVersion === rev.version && (
                      <div className="mt-3 border-t border-border pt-3">
                        {busy === `version-${rev.version}` && !versionDetails[rev.version] ? (
                          <p className="text-sm text-muted-foreground">Loading...</p>
                        ) : (
                          versionDetails[rev.version] && (
                            <>
                              <Markdown text={versionDetails[rev.version].executive_summary} />
                              {!!versionDetails[rev.version].recommendations?.length && (
                                <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-muted-foreground">
                                  {versionDetails[rev.version].recommendations!.map((rec, i) => (
                                    <li key={i}>
                                      <Markdown text={rec} className="inline text-inherit [&_p]:inline" />
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </>
                          )
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-6">
            <h2 className="font-medium text-foreground">Feedback</h2>
            <p className="mb-3 mt-1 text-sm text-muted-foreground">
              Leave an optional comment and click "Looks good" for a quick thumbs up, or describe what
              should change and click "Request changes" - an AI pass decides which section(s) your
              feedback concerns (executive summary, risk summary, migration waves, or recommendations)
              and revises only those, leaving the rest untouched. Each revision is saved to version
              history above.
            </p>
            <Textarea
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="e.g. Call out the database migration risk more clearly in the summary."
              rows={3}
              className="mb-3"
            />
            <div className="flex gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={handleLooksGood}
                disabled={busy === "feedback" || busy === "revise"}
                className={cn(
                  report.feedback_rating === "up" && "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
                )}
              >
                {busy === "feedback" ? "Recording..." : "Looks good"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={handleRequestChanges}
                disabled={busy === "revise" || busy === "feedback" || !feedbackText.trim()}
                className={cn(
                  report.feedback_rating === "down" && "border-rose-500/30 bg-rose-500/15 text-rose-300",
                )}
              >
                {busy === "revise" ? "Revising..." : "Request changes"}
              </Button>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
