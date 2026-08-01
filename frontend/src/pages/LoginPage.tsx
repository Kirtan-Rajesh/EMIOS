import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Card } from "@/components/Card";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

/** Phase 1: User -> React Web UI -> POST /auth/login (or /auth/register). */
export function LoginPage() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    return <Navigate to="/dashboard" replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 text-foreground">
      <div className="pointer-events-none fixed inset-0 hidden dark:block dark:bg-noise dark:opacity-[0.04]" />
      <div className="pointer-events-none fixed inset-0 hidden overflow-hidden dark:block">
        <div className="absolute -left-40 -top-40 h-96 w-96 rounded-full bg-[#30E3CA]/[0.13] blur-3xl" />
        <div className="absolute -right-40 top-20 h-96 w-96 rounded-full bg-[#FF204E]/[0.09] blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-96 w-96 rounded-full bg-[#DA0037]/[0.06] blur-3xl" />
      </div>

      <Link
        to="/"
        className="absolute left-6 top-6 font-mono-ui text-xs text-muted-foreground transition hover:text-foreground"
      >
        ← EMIOS
      </Link>

      <Card className="relative w-full max-w-sm p-8">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-border bg-primary text-primary-foreground dark:bg-gradient-to-br dark:from-[#17181a] dark:to-[#0c0c0d] dark:text-[#FF204E]">
            <BrandMark className="h-4.5 w-4.5" />
          </span>
          <div>
            <p className="font-display text-sm font-semibold leading-none tracking-wide text-foreground">EMIOS</p>
            <p className="mt-1.5 font-mono-ui text-[10px] uppercase tracking-wider leading-none text-muted-foreground">
              Migration Intelligence
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              required
              minLength={mode === "register" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Please wait..." : mode === "login" ? "Log in" : "Create account"}
          </Button>
        </form>
        <Button
          type="button"
          variant="link"
          onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="mt-4 w-full text-muted-foreground hover:text-foreground"
        >
          {mode === "login" ? "Need an account? Register" : "Already have an account? Log in"}
        </Button>
      </Card>
    </div>
  );
}
