import type { ComponentPropsWithoutRef } from "react";
import { cn } from "@/lib/utils";

/** Glass card used throughout the dashboard - token-driven (bg-card/border)
 * so it stays in sync with the shared dark theme in index.css. Forwards
 * arbitrary div props (onClick, etc.) - e.g. the notification panels use
 * onClick to cancel their auto-hide timer on interaction. */
export function Card({ className, ...props }: ComponentPropsWithoutRef<"div">) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-card/60 text-card-foreground shadow-xl shadow-black/20 backdrop-blur-xl",
        className,
      )}
      {...props}
    />
  );
}
