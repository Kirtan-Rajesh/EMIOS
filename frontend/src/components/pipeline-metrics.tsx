import type { ReactNode } from "react";
import { Card } from "@/components/Card";
import type { CloudReadinessMetrics, ComplexityMetrics, EnterpriseRiskMetrics, SimulationMetrics } from "@/types/api";

export function formatUsd(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

export function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export type ScoreTone = "rose" | "amber" | "emerald";

/** Higher-is-worse (complexity/risk) vs higher-is-better (readiness/
 * confidence) scores map to opposite colors at the same magnitude - this
 * picks the right one so a 80% risk score reads as alarming (rose) while an
 * 80% readiness score reads as reassuring (emerald). */
export function toneForScore(value: number, direction: "higher-is-worse" | "higher-is-better"): ScoreTone {
  const pct = value * 100;
  const bucket = pct >= 66 ? "high" : pct >= 33 ? "mid" : "low";
  if (direction === "higher-is-worse") {
    return bucket === "high" ? "rose" : bucket === "mid" ? "amber" : "emerald";
  }
  return bucket === "high" ? "emerald" : bucket === "mid" ? "amber" : "rose";
}

const SCORE_BAR_FILL: Record<ScoreTone, string> = {
  rose: "bg-rose-500",
  amber: "bg-amber-500",
  emerald: "bg-emerald-500",
};

/** Horizontal percentage bar for a single score - used throughout Pipeline
 * metrics (Wave Planner) and the moved Simulation/Recommendation cards
 * (What-If Simulation) wherever a 0-1 score needs to be scanned at a glance
 * rather than read as a raw number. `size="lg"` is for a card's one headline
 * score; plain rows use the default compact size. */
export function ScoreBar({
  label,
  value,
  tone,
  size = "default",
}: {
  label: string;
  value: number;
  tone: ScoreTone;
  size?: "default" | "lg";
}) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className={size === "lg" ? "space-y-1.5" : "space-y-1"}>
      <div className={`flex items-center justify-between ${size === "lg" ? "text-sm" : "text-xs"}`}>
        <span className="text-muted-foreground">{label}</span>
        <span className={`font-medium text-foreground ${size === "lg" ? "text-base" : ""}`}>{pct}%</span>
      </div>
      <div className={`w-full overflow-hidden rounded-full bg-muted/40 ${size === "lg" ? "h-2.5" : "h-1.5"}`}>
        <div
          className={`h-full rounded-full ${SCORE_BAR_FILL[tone]} transition-[width]`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-center">
      <p className="text-sm font-medium text-foreground">{value}</p>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
    </div>
  );
}

export function Badge({ tone, children }: { tone: "amber" | "rose" | "emerald" | "slate"; children: ReactNode }) {
  const styles: Record<string, string> = {
    amber: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    rose: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    emerald: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    slate: "border-border bg-muted/30 text-foreground/80",
  };
  return <span className={`rounded-full border px-2.5 py-1 text-xs ${styles[tone]}`}>{children}</span>;
}

/** Shared field list for the four free-text recommendation fields - used both
 * by PlannerPage's per-agent Recommendation Agent card (raw RecommendationAgentOutput)
 * and the pipeline-level RecommendationCard below (authoritative RecommendationMetrics);
 * both types use these exact field names, so callers index with a cast. */
export const RECOMMENDATION_FIELDS: { key: string; label: string }[] = [
  { key: "engineering_recommendation", label: "Engineering" },
  { key: "business_recommendation", label: "Business" },
  { key: "modernization_recommendation", label: "Modernization" },
  { key: "customer_recommendation", label: "Customer-facing" },
];

/** The 12-agent pipeline's per-strategy (rehost/replatform/refactor/etc) cost-
 * benefit comparison - distinct from What-If Simulation's own single-service
 * cascading-failure Monte Carlo forecast on this same page; this one compares
 * migration strategies, that one stress-tests one topology change. */
export function SimulationScenariosCard({ simulationResults }: { simulationResults: SimulationMetrics }) {
  if (!Object.keys(simulationResults.scenarios ?? {}).length) return null;
  return (
    <Card className="p-5">
      <h3 className="mb-3 font-medium text-foreground">Simulation scenarios</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(simulationResults.scenarios).map(([strategy, scenario]) => (
          <div key={strategy} className="rounded-lg border border-border bg-muted/10 p-3">
            <p className="mb-2.5 font-medium text-foreground">{titleCase(strategy)}</p>
            <div className="mb-3 space-y-2">
              <ScoreBar label="Risk" value={scenario.risk} tone={toneForScore(scenario.risk, "higher-is-worse")} />
              <ScoreBar
                label="Confidence"
                value={scenario.confidence}
                tone={toneForScore(scenario.confidence, "higher-is-better")}
              />
              <ScoreBar
                label="Cloud readiness"
                value={scenario.cloud_readiness}
                tone={toneForScore(scenario.cloud_readiness, "higher-is-better")}
              />
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              <StatChip label="Duration" value={`${scenario.duration_days}d`} />
              <StatChip label="Cost" value={formatUsd(scenario.cost_usd)} />
              <StatChip label="Eng days" value={String(scenario.engineering_effort_days)} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Complexity Assessment Agent's scoring - moved here from Wave Planner's
 * Pipeline metrics onto the Overview page, alongside the other whole-system
 * KPIs (readiness, cost, risk), rather than living behind a planner run. */
export function ComplexityCard({ complexity }: { complexity: ComplexityMetrics }) {
  return (
    <Card className="p-5">
      <h3 className="mb-3 font-medium text-foreground">Complexity</h3>
      <div className="mb-4">
        <ScoreBar
          label="Overall complexity"
          value={complexity.complexity_score}
          tone={toneForScore(complexity.complexity_score, "higher-is-worse")}
          size="lg"
        />
      </div>
      <div className="mb-4 grid grid-cols-1 gap-x-4 gap-y-2.5 sm:grid-cols-2">
        {Object.entries(complexity.dimension_scores ?? {}).map(([dim, score]) => (
          <ScoreBar key={dim} label={titleCase(dim)} value={score} tone={toneForScore(score, "higher-is-worse")} />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <StatChip label="Eng days" value={String(complexity.engineering_effort_days)} />
        <StatChip label="Weeks" value={String(complexity.estimated_timeline_weeks)} />
        <StatChip label="Team size" value={String(complexity.team_size)} />
      </div>
    </Card>
  );
}

/** Risk Assessment Agent's 8-category enterprise risk scoring - moved here
 * from Wave Planner's Pipeline metrics for the same reason as ComplexityCard. */
export function EnterpriseRiskCard({ enterpriseRisk }: { enterpriseRisk: EnterpriseRiskMetrics }) {
  return (
    <Card className="p-5">
      <h3 className="mb-3 font-medium text-foreground">Enterprise risk</h3>
      <div className="mb-4">
        <ScoreBar
          label="Overall risk"
          value={enterpriseRisk.risk_score}
          tone={toneForScore(enterpriseRisk.risk_score, "higher-is-worse")}
          size="lg"
        />
      </div>
      <div className="mb-4 grid grid-cols-1 gap-x-4 gap-y-2.5 sm:grid-cols-2">
        {Object.entries(enterpriseRisk.category_scores ?? {}).map(([cat, score]) => (
          <ScoreBar key={cat} label={titleCase(cat)} value={score} tone={toneForScore(score, "higher-is-worse")} />
        ))}
      </div>
      {!!enterpriseRisk.top_risks?.length && (
        <ul className="mb-3 list-inside list-disc space-y-1.5 text-sm leading-relaxed text-foreground/80">
          {enterpriseRisk.top_risks.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {!!enterpriseRisk.mitigation_strategies?.length && (
        <div>
          <p className="mb-1.5 text-xs uppercase tracking-wide text-muted-foreground">Mitigations</p>
          <ul className="list-inside list-disc space-y-1.5 text-sm leading-relaxed text-foreground/80">
            {enterpriseRisk.mitigation_strategies.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

/** Cloud Readiness Agent's platform-fit scoring - moved here from Wave
 * Planner's Pipeline metrics for the same reason as ComplexityCard. */
export function CloudReadinessCard({ cloudReadiness }: { cloudReadiness: CloudReadinessMetrics }) {
  return (
    <Card className="p-5">
      <h3 className="mb-3 font-medium text-foreground">Cloud readiness</h3>
      <div className="mb-4">
        <ScoreBar
          label="Overall readiness"
          value={cloudReadiness.readiness_score}
          tone={toneForScore(cloudReadiness.readiness_score, "higher-is-better")}
          size="lg"
        />
      </div>
      <div className="mb-4 space-y-2.5">
        {Object.entries(cloudReadiness.platform_scores ?? {}).map(([platform, score]) => (
          <ScoreBar key={platform} label={platform} value={score} tone={toneForScore(score, "higher-is-better")} />
        ))}
      </div>
      {cloudReadiness.recommended_platform && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-sm">
          <span className="text-muted-foreground">Recommended:</span>
          <span className="font-medium text-foreground">{cloudReadiness.recommended_platform}</span>
        </div>
      )}
    </Card>
  );
}
