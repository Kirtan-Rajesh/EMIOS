import type { DiscoveryEvent } from "@/types/api";
import type { ExtractionStep } from "@/components/ExtractionProgressModal";

/** Renders one DiscoveryEvent as a single human-readable log line - shared by
 * DocumentsPage's inline log and DiscoveryRunPanel's floating status feed. */
export function describeDiscoveryEvent(event: DiscoveryEvent): string {
  switch (event.type) {
    case "start":
      return `Starting discovery — ${event.total_documents} document${event.total_documents === 1 ? "" : "s"} to process.`;
    case "document_start":
      return `[${event.index}/${event.total}] Processing ${event.filename}...`;
    case "document_result":
      return `  → ${event.extractor} found ${event.nodes_found} system${event.nodes_found === 1 ? "" : "s"} and ${event.edges_found} dependenc${event.edges_found === 1 ? "y" : "ies"} (confidence ${Math.round(event.confidence * 100)}%).`;
    case "merging":
      return event.message;
    case "csv_generated":
      return `Generated nodes.csv (${event.node_count} rows) and edges.csv (${event.edge_count} rows).`;
    case "persisting":
      return event.message;
    case "complete":
      return event.status === "no_data_extracted"
        ? "No systems or dependencies could be extracted from the uploaded documents."
        : `Done — ${event.node_count} systems, ${event.edge_count} dependencies persisted to the digital twin.`;
    case "error":
      return `Error: ${event.message}`;
    default:
      return "Processing...";
  }
}

/** Converts a raw DiscoveryEvent stream into ExtractionProgressModal-shaped
 * steps + an overall percent - the same transform NewAssessmentPage used to
 * do inline against its own local event handler, now shared so both it and
 * any other discovery-driven progress UI stay in sync. Pure function of the
 * full event list so far (recomputed on every new event, not incremental
 * state) - cheap at the event volumes a single discovery run produces. */
export function discoveryEventsToProgress(events: DiscoveryEvent[]): { steps: ExtractionStep[]; percent: number } {
  const steps: ExtractionStep[] = [];
  let percent = 0;
  const stepIndex = new Map<string, number>();

  function upsert(step: ExtractionStep) {
    const existingIndex = stepIndex.get(step.id);
    if (existingIndex !== undefined) {
      steps[existingIndex] = step;
    } else {
      stepIndex.set(step.id, steps.length);
      steps.push(step);
    }
  }

  for (const event of events) {
    if (event.type === "start") {
      upsert({
        id: "prepare",
        label: `Preparing ${event.total_documents} document${event.total_documents === 1 ? "" : "s"}`,
        status: "done",
      });
      percent = 6;
    } else if (event.type === "document_start") {
      upsert({
        id: `doc-${event.filename}`,
        label: event.filename,
        detail: `Analyzing (${event.index}/${event.total})`,
        status: "active",
      });
      percent = 6 + Math.round(((event.index - 1) / event.total) * 74);
    } else if (event.type === "document_result") {
      const existing = steps[stepIndex.get(`doc-${event.filename}`) ?? -1];
      upsert({
        id: `doc-${event.filename}`,
        label: event.filename,
        detail: `${event.nodes_found} nodes · ${event.edges_found} edges · ${Math.round(event.confidence * 100)}% confidence`,
        status: "done",
      });
      void existing;
    } else if (event.type === "merging") {
      upsert({ id: "merging", label: "Merging results", detail: event.message, status: "active" });
      percent = 82;
    } else if (event.type === "csv_generated") {
      upsert({
        id: "merging",
        label: "Merging results",
        detail: `${event.node_count} nodes · ${event.edge_count} edges merged`,
        status: "done",
      });
      percent = 88;
    } else if (event.type === "persisting") {
      upsert({ id: "persisting", label: "Saving to the digital twin graph", detail: event.message, status: "active" });
      percent = 95;
    } else if (event.type === "complete") {
      const graphBuilt = event.status === "graph_updated";
      upsert({
        id: "persisting",
        label: "Saving to the digital twin graph",
        detail: graphBuilt ? `${event.node_count} nodes · ${event.edge_count} edges saved` : "No systems extracted",
        status: "done",
      });
      percent = 100;
    } else if (event.type === "error") {
      const activeIndex = [...stepIndex.entries()].find(([, i]) => steps[i]?.status === "active")?.[1];
      if (activeIndex !== undefined) {
        steps[activeIndex] = { ...steps[activeIndex], status: "error", detail: event.message };
      }
    }
  }

  return { steps, percent };
}
