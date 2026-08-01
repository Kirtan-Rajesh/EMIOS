import * as DialogPrimitive from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type ExtractionStepStatus = "pending" | "active" | "done" | "error";

export interface ExtractionStep {
  id: string;
  label: string;
  detail?: string;
  status: ExtractionStepStatus;
}

function StepIcon({ status }: { status: ExtractionStepStatus }) {
  if (status === "done") return <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />;
  if (status === "active") return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />;
  if (status === "error") return <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />;
  return <Circle className="h-4 w-4 shrink-0 text-muted-foreground/40" />;
}

/**
 * Non-dismissible progress panel for long-running, multi-file operations
 * (zip extraction, document discovery) - shows the live percentage plus a
 * step-by-step feed of what's actually being processed, instead of cramming
 * a single ever-growing status string into a button label.
 *
 * Anchored bottom-right (same corner/offset as the PlannerRunPanel/
 * DiscoveryRunPanel stack in App.tsx) rather than as a dead-center, screen-
 * blocking dialog: there's no dark overlay, so the rest of the page stays
 * visible and interactive behind it. It's still non-dismissible (no close
 * button, Escape/outside-click are suppressed) because the underlying
 * upload/extraction really shouldn't be navigated away from mid-flight, but
 * that's now a soft convention rather than an enforced screen takeover.
 */
export function ExtractionProgressModal({
  open,
  title,
  subtitle,
  percent,
  steps,
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  percent: number;
  steps: ExtractionStep[];
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={() => undefined}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          onEscapeKeyDown={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed bottom-4 right-4 z-50 w-80 max-w-[calc(100vw-2rem)] rounded-2xl border border-border bg-card/40 p-6 shadow-2xl shadow-black/50 backdrop-blur-2xl outline-none data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <DialogPrimitive.Title className="font-display text-base font-semibold text-foreground">
                {title}
              </DialogPrimitive.Title>
              {subtitle && (
                <DialogPrimitive.Description className="mt-1 text-xs text-muted-foreground">
                  {subtitle}
                </DialogPrimitive.Description>
              )}
            </div>
            <span className="shrink-0 rounded-full bg-secondary px-2.5 py-1 font-mono-ui text-xs font-semibold tabular-nums text-primary">
              {Math.round(percent)}%
            </span>
          </div>

          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-secondary">
            <motion.div
              className="h-full rounded-full bg-primary dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E]"
              animate={{ width: `${Math.max(3, Math.min(100, percent))}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            />
          </div>

          <div className="scrollbar-thin mt-4 max-h-72 space-y-1.5 overflow-y-auto pr-1">
            <AnimatePresence initial={false}>
              {steps.map((step) => (
                <motion.div
                  key={step.id}
                  initial={{ opacity: 0, y: -6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25 }}
                  className={cn(
                    "flex items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-2 text-xs",
                    step.status === "active" && "border-primary/25 bg-primary/5",
                    step.status === "error" && "border-destructive/25 bg-destructive/5",
                  )}
                >
                  <span className="mt-0.5">
                    <StepIcon status={step.status} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        "block truncate font-medium",
                        step.status === "pending" ? "text-muted-foreground" : "text-foreground",
                      )}
                    >
                      {step.label}
                    </span>
                    {step.detail && (
                      <span
                        className={cn(
                          "mt-0.5 block truncate font-mono-ui text-[10.5px]",
                          step.status === "error" ? "text-destructive" : "text-muted-foreground",
                        )}
                      >
                        {step.detail}
                      </span>
                    )}
                  </span>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          <p className="mt-4 text-center text-[11px] text-muted-foreground">
            This can take a minute for larger archives - keep this tab open.
          </p>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
