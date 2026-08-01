import { useEffect, useId, useRef, useState } from "react";

let mermaidInitialized = false;

/** Lazily imports and configures mermaid.js once per page load (it's a sizable
 * dependency - no reason to pull it into the initial bundle for pages that
 * never render a flowchart), then renders a single ```mermaid fenced code
 * block (see Markdown.tsx's `code` renderer) to inline SVG. Used for
 * structural diagrams a table/bullet list can't express well - a circular
 * dependency chain, a migration wave sequence - never as the default for
 * plain narrative content. */
export function MermaidDiagram({ chart }: { chart: string }) {
  const id = useId().replace(/:/g, "-");
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const { default: mermaid } = await import("mermaid");
        if (!mermaidInitialized) {
          mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
          mermaidInitialized = true;
        }
        const { svg } = await mermaid.render(`mermaid-${id}`, chart.trim());
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      } catch {
        if (!cancelled) setError("Diagram could not be rendered.");
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [chart, id]);

  if (error) {
    return <pre className="overflow-x-auto rounded-md border border-border bg-input/20 p-2 text-xs">{chart}</pre>;
  }

  return <div ref={containerRef} className="my-2 flex justify-center overflow-x-auto rounded-md border border-border bg-input/10 p-3" />;
}
