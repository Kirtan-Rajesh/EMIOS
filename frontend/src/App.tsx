import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { DiscoveryRunPanel } from "@/components/DiscoveryRunPanel";
import { PlannerRunPanel } from "@/components/PlannerRunPanel";
import { ReportRunPanel } from "@/components/ReportRunPanel";
import { RequireAuth } from "@/components/RequireAuth";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/lib/auth-context";
import { DiscoveryRunProvider } from "@/lib/discovery-run-context";
import { PlannerRunProvider } from "@/lib/planner-run-context";
import { ReportRunProvider } from "@/lib/report-run-context";
import { ThemeProvider } from "@/lib/theme-context";
import { DashboardPage } from "@/pages/DashboardPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { GraphPage } from "@/pages/GraphPage";
import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { NewAssessmentPage } from "@/pages/NewAssessmentPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { PlannerPage } from "@/pages/PlannerPage";
import { ReportPage } from "@/pages/ReportPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SimulatePage } from "@/pages/SimulatePage";

/**
 * Every authenticated route lives under one persistent sidebar (`AppShell`) -
 * no separate top-navbar/sidebar split. Backend phases still map onto it:
 *   /                                   Public marketing homepage
 *   /login                              Phase 1 (login)
 *   /dashboard                          Phase 1 end-state / Phase 2 entry point
 *   /assessments/new                    Phase 2 (create assessment)
 *   /settings                           Account details
 *   /assessments/:id                    Overview dashboard (KPIs, charts, inventory)
 *   /assessments/:id/documents          Phase 3 (document upload -> S3 -> RAG index)
 *   /assessments/:id/graph              Digital twin topology + visualization
 *   /assessments/:id/simulate           What-if cascading-failure simulation
 *   /assessments/:id/planner            Phases 4-7 (Discovery/Dependency/Planner/Risk agents)
 *   /assessments/:id/report             Phase 7 display, 8 (feedback), 9 (final plan)
 */
export default function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <Toaster position="top-right" closeButton />
        <BrowserRouter>
          <PlannerRunProvider>
            <ReportRunProvider>
              <DiscoveryRunProvider>
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route element={<RequireAuth />}>
                    <Route element={<AppShell />}>
                      <Route path="/dashboard" element={<DashboardPage />} />
                      <Route path="/assessments/new" element={<NewAssessmentPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="/assessments/:id" element={<OverviewPage />} />
                      <Route path="/assessments/:id/documents" element={<DocumentsPage />} />
                      <Route path="/assessments/:id/graph" element={<GraphPage />} />
                      <Route path="/assessments/:id/simulate" element={<SimulatePage />} />
                      <Route path="/assessments/:id/planner" element={<PlannerPage />} />
                      <Route path="/assessments/:id/report" element={<ReportPage />} />
                    </Route>
                  </Route>
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
                {/* Single bottom-right notification column, separate from the
                 * sonner Toaster's own top-right toast stack (quick one-shot
                 * confirmations vs. these persistent live-run panels) - anchored
                 * at the bottom so the column grows upward as panels stack,
                 * never colliding with the toasts up top. */}
                <div className="fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-3">
                  <PlannerRunPanel />
                  <ReportRunPanel />
                  <DiscoveryRunPanel />
                </div>
              </DiscoveryRunProvider>
            </ReportRunProvider>
          </PlannerRunProvider>
        </BrowserRouter>
      </ThemeProvider>
    </AuthProvider>
  );
}
