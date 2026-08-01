import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PipelineMetricsSection } from "@/pages/PlannerPage";
import type { RunPlannerResponse } from "@/types/api";

const BASE_RESULT: RunPlannerResponse = {
  assessment_id: "a1",
  waves: [],
  decoupling_strategies: [],
  risk_assessment: {},
  agent_runs: [],
};

describe("PipelineMetricsSection", () => {
  it("renders nothing when there's no explainability data and no confidence score", () => {
    const { container } = render(<PipelineMetricsSection result={BASE_RESULT} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the overall confidence score as a percentage", () => {
    render(<PipelineMetricsSection result={{ ...BASE_RESULT, confidence_score: 0.82 }} />);
    expect(screen.getByText("Overall confidence")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
  });

  it("renders explainability evidence, dependencies, and risks considered", () => {
    render(
      <PipelineMetricsSection
        result={{
          ...BASE_RESULT,
          explainability: {
            evidence: ["High coupling between order-service and payment-service"],
            dependencies_considered: ["order-service"],
            risks_considered: ["shared-database"],
            confidence_explanation: "Grounded in the discovered dependency graph.",
          },
        }}
      />,
    );
    expect(screen.getByText("Explainability")).toBeInTheDocument();
    expect(screen.getByText("Grounded in the discovered dependency graph.")).toBeInTheDocument();
    expect(screen.getByText("High coupling between order-service and payment-service")).toBeInTheDocument();
    expect(screen.getByText("order-service")).toBeInTheDocument();
    expect(screen.getByText("shared-database")).toBeInTheDocument();
  });
});
