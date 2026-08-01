import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2, Layers, Plus, TrendingUp } from "lucide-react";
import { Card } from "@/components/Card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { v1Api } from "@/lib/api";
import type { Assessment, DashboardSummary } from "@/types/api";

const STATUS_VARIANT: Record<string, "neutral" | "blue" | "amber" | "emerald" | "rose"> = {
  created: "neutral",
  uploading: "blue",
  analyzing: "amber",
  complete: "emerald",
  failed: "rose",
};

function StatCard({ icon: Icon, label, value }: { icon: typeof Layers; label: string; value: number | string }) {
  return (
    <Card className="flex items-center gap-3 p-4 shadow-sm">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 dark:bg-gradient-to-br dark:from-[#30E3CA]/20 dark:to-[#FF204E]/10">
        <Icon className="h-5 w-5 text-primary" />
      </span>
      <div>
        <p className="text-xl font-semibold text-foreground">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </Card>
  );
}

/** Phase 1 end-state / entry point for Phase 2 (Create Migration Assessment).
 * The sidebar already lists assessments for quick switching - this page is
 * the richer portfolio view (status, target cloud, summary stats). */
export function DashboardPage() {
  const [assessments, setAssessments] = useState<Assessment[] | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    v1Api
      .listAssessments()
      .then(setAssessments)
      .catch(() => setError("Could not load assessments."));
    v1Api
      .dashboardSummary()
      .then(setSummary)
      .catch(() => undefined);
  }, []);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Assessments</h1>
          <p className="mt-1 text-sm text-muted-foreground">Pick one to open its dashboard, or start a new one.</p>
        </div>
        <Button asChild>
          <Link to="/assessments/new">
            <Plus className="h-4 w-4" /> New assessment
          </Link>
        </Button>
      </div>

      {summary && (
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard icon={Layers} label="Total assessments" value={summary.total_assessments} />
          <StatCard icon={TrendingUp} label="In progress" value={summary.active_assessments} />
          <StatCard icon={CheckCircle2} label="Completed" value={summary.completed_assessments} />
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!assessments && !error && <p className="text-sm text-muted-foreground">Loading...</p>}
      {assessments && assessments.length === 0 && (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          No assessments yet - create one to get started.
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {assessments?.map((a) => (
          <Link key={a.assessment_id} to={`/assessments/${a.assessment_id}`}>
            <Card className="group p-5 shadow-sm transition hover:border-primary/30 hover:shadow-md hover:bg-accent/50 dark:hover:bg-white/[0.07]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{a.project_name}</p>
                  <p className="mt-0.5 truncate text-sm text-muted-foreground">
                    {a.customer_name} · target: {a.target_cloud}
                  </p>
                </div>
                <Badge variant={STATUS_VARIANT[a.status] ?? "neutral"}>{a.status}</Badge>
              </div>
              <div className="mt-4 flex items-center gap-1 text-xs font-medium text-primary opacity-0 transition group-hover:opacity-100">
                Open dashboard <ArrowRight className="h-3 w-3" />
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
