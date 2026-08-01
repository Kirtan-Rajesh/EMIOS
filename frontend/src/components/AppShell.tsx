import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  FileBarChart,
  FolderOpen,
  Gauge,
  GitBranch,
  Layers,
  LayoutDashboard,
  LogOut,
  Moon,
  Network,
  Plus,
  Settings as SettingsIcon,
  Sparkles,
  Sun,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { useTheme } from "@/lib/theme-context";
import { v1Api } from "@/lib/api";
import type { Assessment } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ExecutiveCopilot } from "@/components/ExecutiveCopilot";
import { BrandMark } from "@/components/BrandMark";
import { ErrorBoundary } from "@/components/ErrorBoundary";

/** Light/dark segmented control - lives at the top of the account dropdown
 * (opened by clicking the user's email in the sidebar), above "Settings".
 * Plain buttons rather than DropdownMenuItem so clicking it doesn't close
 * the menu, letting you see the theme actually change before dismissing it. */
function ThemeToggleRow() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="flex items-center justify-between gap-2 px-2 py-1.5">
      <span className="flex items-center gap-2 text-sm text-foreground">
        {theme === "dark" ? <Moon className="h-4 w-4 text-muted-foreground" /> : <Sun className="h-4 w-4 text-muted-foreground" />}
        Theme
      </span>
      <div className="flex items-center gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5">
        <button
          type="button"
          onClick={() => setTheme("light")}
          className={cn(
            "rounded-md px-2 py-1 text-xs font-medium transition",
            theme === "light" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          Light
        </button>
        <button
          type="button"
          onClick={() => setTheme("dark")}
          className={cn(
            "rounded-md px-2 py-1 text-xs font-medium transition",
            theme === "dark" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          Dark
        </button>
      </div>
    </div>
  );
}

const ASSESSMENT_NAV = [
  { to: "", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "documents", label: "Documents", icon: FolderOpen, end: false },
  { to: "graph", label: "Digital Twin Graph", icon: Network, end: false },
  { to: "simulate", label: "What-If Simulation", icon: Gauge, end: false },
  { to: "planner", label: "Wave Planner", icon: GitBranch, end: false },
  { to: "report", label: "Report", icon: FileBarChart, end: false },
];

function initialsFor(email?: string): string {
  if (!email) return "?";
  return email.slice(0, 2).toUpperCase();
}

/**
 * Single persistent sidebar shell for the whole authenticated app. Content is
 * contextual based on the URL alone (not route nesting):
 *  - Outside any assessment (/dashboard, /assessments/new, /settings): the
 *    sidebar just shows a link back to the assessments list + "New" - the
 *    full list itself lives on the Dashboard page, not duplicated here.
 *  - Inside one (/assessments/:id/*): the sidebar is that assessment's own
 *    tab navigation (Overview/Documents/Graph/Simulate/Planner/Report).
 * The account menu (Settings, Log out) is pinned at the bottom in both modes.
 */
export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const assessmentId = useMemo(() => {
    const match = location.pathname.match(/^\/assessments\/([^/]+)/);
    if (!match || match[1] === "new") return null;
    return match[1];
  }, [location.pathname]);

  const [currentAssessment, setCurrentAssessment] = useState<Assessment | null>(null);
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => {
    if (!assessmentId) {
      setCurrentAssessment(null);
      setCopilotOpen(false);
      return;
    }
    v1Api
      .getAssessment(assessmentId)
      .then(setCurrentAssessment)
      .catch(() => setCurrentAssessment(null));
  }, [assessmentId]);

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  const accountMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-sidebar-accent"
        >
          <Avatar className="size-8">
            <AvatarFallback className="bg-primary font-mono-ui text-[11px] font-bold text-primary-foreground">
              {initialsFor(user?.email)}
            </AvatarFallback>
          </Avatar>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs text-sidebar-foreground/70">{user?.email}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <ThemeToggleRow />
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <SettingsIcon className="h-4 w-4" /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={handleLogout}>
          <LogOut className="h-4 w-4" /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
      isActive
        ? "border border-sidebar-border bg-sidebar-accent text-sidebar-foreground before:absolute before:-left-4 before:top-1/2 before:h-[58%] before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-primary dark:before:shadow-[0_0_8px_#30E3CA]"
        : "text-muted-foreground transition-transform hover:translate-x-0.5 hover:bg-sidebar-accent hover:text-sidebar-foreground",
    );

  return (
    <div className="min-h-screen bg-background text-foreground antialiased">
      {/* Dark theme's "mission control" glow/noise treatment - not part of
       * the light theme, so scoped entirely to dark: rather than always
       * rendered - see index.css's .bg-noise/.dark for what these use. */}
      <div className="pointer-events-none fixed inset-0 hidden overflow-hidden dark:block dark:bg-noise dark:opacity-[0.04]" />
      <div className="pointer-events-none fixed inset-0 hidden overflow-hidden dark:block">
        <div className="absolute -left-40 -top-40 h-96 w-96 rounded-full bg-[#30E3CA]/[0.14] blur-3xl" />
        <div className="absolute -right-40 top-20 h-96 w-96 rounded-full bg-[#FF204E]/[0.10] blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-96 w-96 rounded-full bg-[#DA0037]/[0.07] blur-3xl" />
      </div>

      <div className="relative flex">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar/80 px-4 py-6 text-sidebar-foreground backdrop-blur-xl lg:flex">
          <Link to="/dashboard" className="flex items-center gap-2.5 px-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm dark:border dark:border-border dark:bg-gradient-to-br dark:from-[#17181a] dark:to-[#0c0c0d] dark:text-[#FF204E] dark:shadow-lg dark:shadow-black/40">
              <BrandMark className="h-5 w-5 dark:h-4.5 dark:w-4.5" />
            </span>
            <span>
              <span className="block font-display text-sm font-semibold leading-none tracking-wide text-sidebar-foreground">
                EMIOS
              </span>
              <span className="block font-mono-ui text-[10px] uppercase tracking-wider leading-none text-muted-foreground mt-1.5">
                Migration Intelligence
              </span>
            </span>
          </Link>

          <div className="scrollbar-thin mt-6 flex-1 overflow-y-auto overflow-x-hidden">
            {assessmentId ? (
              <>
                <Link
                  to="/dashboard"
                  className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition hover:bg-sidebar-accent hover:text-sidebar-foreground"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> All assessments
                </Link>
                <div className="mt-3 px-2">
                  <p className="truncate text-xs uppercase tracking-wider text-muted-foreground">
                    {currentAssessment?.customer_name ?? "Loading..."}
                  </p>
                  <p className="truncate text-sm font-semibold text-sidebar-foreground">
                    {currentAssessment?.project_name ?? " "}
                  </p>
                </div>

                <nav className="mt-5 flex flex-col gap-1">
                  {ASSESSMENT_NAV.map((item) => {
                    const Icon = item.icon;
                    return (
                      <NavLink
                        key={item.label}
                        to={`/assessments/${assessmentId}${item.to ? `/${item.to}` : ""}`}
                        end={item.end}
                        className={navLinkClass}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </NavLink>
                    );
                  })}
                </nav>
              </>
            ) : (
              <nav className="flex flex-col gap-1">
                <NavLink to="/dashboard" className={navLinkClass}>
                  <Layers className="h-4 w-4" />
                  Assessments
                </NavLink>
                <Button
                  asChild
                  variant="ghost"
                  className="justify-start gap-3 px-3 text-sm font-medium text-muted-foreground hover:text-sidebar-foreground"
                >
                  <Link to="/assessments/new">
                    <Plus className="h-4 w-4" /> New assessment
                  </Link>
                </Button>
              </nav>
            )}
          </div>

          {assessmentId && (
            <button
              type="button"
              data-copilot-trigger
              onClick={() => setCopilotOpen((v) => !v)}
              className={cn(
                "mt-3 flex items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all",
                "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar",
                copilotOpen
                  ? "border-transparent bg-primary text-primary-foreground shadow-sm dark:bg-gradient-to-r dark:from-[#30E3CA] dark:to-[#FF204E] dark:shadow-lg dark:shadow-[#FF204E]/20"
                  : "border-sidebar-border text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Sparkles className="h-4 w-4 shrink-0" />
              Executive Copilot
            </button>
          )}

          <div className="mt-4 border-t border-sidebar-border pt-4">{accountMenu}</div>
        </aside>

        <main className="min-w-0 flex-1 px-6 py-6 lg:px-8">
          <div className="mb-4 flex items-center justify-between lg:hidden">
            <span className="text-sm font-semibold text-foreground">
              {assessmentId ? (currentAssessment?.project_name ?? "Loading...") : "EMIOS"}
            </span>
            <div className="flex items-center gap-3">
              {assessmentId && (
                <button
                  type="button"
                  data-copilot-trigger
                  onClick={() => setCopilotOpen((v) => !v)}
                  className="flex items-center gap-1.5 text-xs font-medium text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background rounded"
                  aria-label="Toggle Executive Copilot"
                >
                  <Sparkles className="h-3.5 w-3.5" /> Copilot
                </button>
              )}
              <button type="button" onClick={handleLogout} className="text-xs text-muted-foreground">
                Log out
              </button>
            </div>
          </div>
          {/* Keyed by pathname so navigating to a different route remounts the
           * boundary (resets hasError) - otherwise, once one page's render
           * throws, every subsequent page would keep showing the same
           * fallback until a full reload, since Outlet's *content* changes
           * across navigation but the boundary instance itself wouldn't. */}
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      {assessmentId && (
        // key={assessmentId} forces a fresh mount (fresh messages/context/
        // contextLoaded state) when navigating between assessments - without
        // it, ExecutiveCopilot's own contextLoaded guard never resets, so
        // switching assessments while the panel is mounted kept showing the
        // PREVIOUS assessment's greeting, conversation, and context data
        // under the new one.
        <ExecutiveCopilot key={assessmentId} assessmentId={assessmentId} open={copilotOpen} onOpenChange={setCopilotOpen} />
      )}
    </div>
  );
}
