import { useEffect, useState, type ReactNode } from "react";
import { Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

const STORAGE_PREFIX = "emios_info_dismissed_";

/**
 * A restrained "what is this / what should I do here" explainer, for a
 * first-time user navigating an otherwise fairly dense enterprise tool - not
 * a garish warning banner, just a quiet callout with an icon and a couple of
 * sentences. Dismissible and remembers that per browser (per `id`, via
 * localStorage) so it never nags a returning user who already knows the
 * page - onboarding copy that stays out of the way once it's done its job.
 */
export function InfoBanner({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const storageKey = `${STORAGE_PREFIX}${id}`;
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(localStorage.getItem(storageKey) === "1");
  }, [storageKey]);

  if (dismissed) return null;

  function handleDismiss() {
    localStorage.setItem(storageKey, "1");
    setDismissed(true);
  }

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border border-primary/20 bg-primary/[0.05] p-4",
      )}
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/15">
        <Info className="h-4 w-4 text-primary" />
      </span>
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-foreground/80">
        <p className="font-medium text-foreground">{title}</p>
        <div className="mt-1">{children}</div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        className="shrink-0 text-muted-foreground transition hover:text-foreground"
        aria-label="Dismiss"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
