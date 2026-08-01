import type { ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MermaidDiagram } from "@/components/MermaidDiagram";
import { cn } from "@/lib/utils";

/**
 * Renders LLM-authored markdown (report executive summaries, migration-plan
 * strategy text, etc.) with real formatting instead of literal `**`/`#`
 * characters - these come back from prompts that explicitly ask for
 * markdown-structured prose (headings, bold, lists), so raw whitespace-pre-wrap
 * text was showing the markdown syntax itself rather than rendering it.
 * Styled inline per-element (not the Tailwind Typography plugin) to match this
 * app's existing muted-foreground/text-sm conventions without a new dependency.
 */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("space-y-2 text-sm text-muted-foreground", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          h1: ({ children }) => <h3 className="mt-3 font-medium text-foreground first:mt-0">{children}</h3>,
          h2: ({ children }) => <h3 className="mt-3 font-medium text-foreground first:mt-0">{children}</h3>,
          h3: ({ children }) => <h4 className="mt-2 font-medium text-foreground first:mt-0">{children}</h4>,
          ul: ({ children }) => <ul className="list-inside list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-inside list-decimal space-y-1">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline hover:no-underline">
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="rounded bg-input/40 px-1 py-0.5 font-mono-ui text-xs text-foreground/90">{children}</code>
          ),
          // A fenced ```mermaid block is parsed as <pre><code class="language-mermaid">
          // - intercept it here (before it hits the default <pre>/`code` styling
          // above, meant for inline code and generic code blocks) and render an
          // actual diagram instead of literal Mermaid syntax text.
          pre: ({ children }) => {
            const codeEl = children as ReactElement<{ className?: string; children?: unknown }> | undefined;
            const codeClassName = codeEl?.props?.className ?? "";
            if (typeof codeClassName === "string" && codeClassName.includes("language-mermaid")) {
              const raw = codeEl?.props?.children;
              const chart = Array.isArray(raw) ? raw.join("") : String(raw ?? "");
              return <MermaidDiagram chart={chart} />;
            }
            return <pre className="overflow-x-auto rounded-md border border-border bg-input/20 p-2 text-xs">{children}</pre>;
          },
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-secondary/60">{children}</thead>,
          tr: ({ children }) => <tr className="border-b border-border last:border-0">{children}</tr>,
          th: ({ children }) => (
            <th className="px-2.5 py-1.5 font-mono-ui text-[10px] uppercase tracking-wide text-muted-foreground">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="px-2.5 py-1.5 align-top text-foreground/80">{children}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
