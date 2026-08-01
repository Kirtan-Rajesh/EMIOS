import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/ui/button";

/** Top-level render-error safety net, wrapping every routed page in AppShell.
 * Before this, the only error boundary anywhere in the app was PlannerPage's
 * own ExplainerBoundary, which only catches a single agent-explainer card's
 * render failure - a throw in any other page (or in PlannerPage outside that
 * one card) had nothing to catch it, unmounting the whole React tree to a
 * blank white screen. This can't fix the underlying error, but it turns "blank
 * page, no idea why" into a page the user can actually act on. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: { componentStack?: string | null }) {
    console.error("Unhandled render error - caught by top-level ErrorBoundary.", error, info.componentStack);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <Card className="flex flex-col items-center gap-3 p-10 text-center">
        <AlertTriangle className="h-6 w-6 text-destructive" />
        <div>
          <p className="font-medium text-foreground">Something went wrong on this page.</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Reloading usually fixes it - if it keeps happening, the details are in the browser console.
          </p>
        </div>
        <Button type="button" onClick={() => window.location.reload()}>
          Reload page
        </Button>
      </Card>
    );
  }
}
