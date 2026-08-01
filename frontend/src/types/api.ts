/**
 * TypeScript mirrors of the backend Pydantic schemas.
 *
 * Legacy surface: backend/app/models/schemas.py  (mounted at /api/*, unwrapped responses)
 * v1 surface:     backend/app/schemas_v1/*.py    (mounted at /api/v1/*, envelope responses)
 */

// ---------------------------------------------------------------------------
// Legacy /api/* surface
// ---------------------------------------------------------------------------

export interface ServiceNode {
  id: string;
  name: string;
  type: string; // Microservice, Monolith, Database, Queue
  business_value: "High" | "Medium" | "Low" | string;
  revenue_impact: number;
  migration_complexity: "High" | "Medium" | "Low" | string;
  base_cost: number;
  base_duration: number;
  status: string; // Legacy, Migrated, Discovered, Orphan
  failure_probability: number;
  runtime?: string | null;
  annual_cost: number;
}

export interface DependencyEdge {
  source: string;
  target: string;
  type: string; // Sync, Async, DB, MQ
  criticality: "High" | "Medium" | "Low" | string;
  is_discovered: boolean;
}

export interface GraphData {
  nodes: ServiceNode[];
  edges: DependencyEdge[];
}

export interface UploadResponseLegacy {
  status: string;
  parsed_nodes_count: number;
  parsed_edges_count: number;
  skipped_count: number;
  warnings: string[];
  errors: string[];
  message: string;
}

export interface SimulationRequest {
  target_id: string;
  already_migrated: string[];
}

export interface MonteCarloDistributionPoint {
  percentile: number;
  duration: number;
  cost: number;
}

export interface MonteCarloResult {
  confidence_90_duration: [number, number];
  confidence_90_cost: [number, number];
  expected_duration: number;
  expected_cost: number;
  distribution: MonteCarloDistributionPoint[];
}

export interface SimulationResponse {
  impacted_services: ServiceNode[];
  critical_paths: string[][];
  revenue_at_risk: number;
  total_impacted_services: number;
  monte_carlo: MonteCarloResult;
  total_hosting_cost: number;
  potential_savings: number;
}

export interface DecouplingStrategy {
  component?: string;
  strategy?: string;
  [key: string]: unknown;
}

export interface NegotiationLogEntry {
  agent?: string;
  message?: string;
  timestamp?: string;
  [key: string]: unknown;
}

export interface PlanningResponse {
  waves: string[][];
  decoupling_strategies: DecouplingStrategy[];
  negotiation_logs: NegotiationLogEntry[];
  risk_assessment: Record<string, RiskAssessmentEntry>;
  trace_id?: string | null;
  observability_summary?: Record<string, unknown> | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  trace_id?: string | null;
}

// ---------------------------------------------------------------------------
// /api/v1/* surface (envelope-wrapped)
// ---------------------------------------------------------------------------

export interface ApiEnvelope<T> {
  success: boolean;
  message: string;
  data?: T;
  errors?: string[];
}

export type AssessmentStatus =
  | "created"
  | "uploading"
  | "analyzing"
  | "complete"
  | "failed";

export interface Assessment {
  assessment_id: string;
  customer_name: string;
  project_name: string;
  target_cloud: string;
  status: AssessmentStatus | string;
  created_at: string;
  updated_at: string;
}

export interface AssessmentCreateRequest {
  customer_name: string;
  project_name: string;
  target_cloud: string;
  status?: AssessmentStatus;
}

export interface AssessmentUpload {
  upload_id: string;
  assessment_id: string;
  filename: string;
  content_type: string;
  uploaded_at: string;
  source_type: string;
  status: string; // uploaded, processing, processed, failed
  chunk_count: number;
}

export interface SkippedZipEntry {
  filename: string;
  reason: string;
}

export interface ZipUploadResponse {
  uploads: AssessmentUpload[];
  skipped: SkippedZipEntry[];
  extracted_count: number;
}

// ---------------------------------------------------------------------------
// Zip upload streaming (/api/v1/assessments/{id}/uploads/zip/stream)
//
// Mirrors backend/app/services_v1/upload_service.py's upload_zip_archive_stream()
// event dicts 1:1 - each Server-Sent Event's `data:` line is exactly one of
// these, discriminated on `type`.
// ---------------------------------------------------------------------------

export interface ZipStreamStartEvent {
  type: "start";
  total: number;
}

export interface ZipStreamMemberStartEvent {
  type: "member_start";
  filename: string;
  index: number;
  total: number;
}

export interface ZipStreamMemberResultEvent {
  type: "member_result";
  filename: string;
  index: number;
  total: number;
  status: string;
  chunk_count: number;
}

export interface ZipStreamMemberSkippedEvent {
  type: "member_skipped";
  filename: string;
  index: number;
  total: number;
  reason: string;
}

export interface ZipStreamCompleteEvent {
  type: "complete";
  extracted_count: number;
  skipped_count: number;
  uploads: AssessmentUpload[];
  skipped: SkippedZipEntry[];
}

export interface ZipStreamErrorEvent {
  type: "error";
  message: string;
}

export type ZipStreamEvent =
  | ZipStreamStartEvent
  | ZipStreamMemberStartEvent
  | ZipStreamMemberResultEvent
  | ZipStreamMemberSkippedEvent
  | ZipStreamCompleteEvent
  | ZipStreamErrorEvent;

export interface MigrationWave {
  wave_id: string;
  assessment_id: string;
  wave_number: number;
  components: string[];
  rationale: string;
  risk_summary?: unknown;
  created_at: string;
}

export interface WaveItem {
  wave_number: number;
  components: string[];
  rationale: string;
  risk_summary?: unknown;
}

export interface DashboardSummary {
  total_assessments: number;
  completed_assessments: number;
  active_assessments: number;
  latest_assessment_id?: string | null;
}

// ---------------------------------------------------------------------------
// Auth (/api/v1/auth/*)
// ---------------------------------------------------------------------------

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthUser {
  user_id: string;
  email: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface CurrentUserResponse {
  user_id: string;
  email: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Assessment Graph Persistence (/api/v1/assessments/{id}/graph)
// ---------------------------------------------------------------------------

export interface GraphPersistResponse {
  assessment_id: string;
  node_count: number;
  edge_count: number;
  graph_status: string;
}

export interface AssessmentGraphResponse {
  assessment_id: string;
  nodes: ServiceNode[];
  edges: DependencyEdge[];
}

// ---------------------------------------------------------------------------
// Document Discovery streaming (/api/v1/assessments/{id}/discover/stream)
//
// Mirrors backend/app/services_v1/discovery_service.py's run_discovery_stream()
// event dicts 1:1 - each Server-Sent Event's `data:` line is exactly one of
// these, discriminated on `type`.
// ---------------------------------------------------------------------------

export interface DiscoveryStartEvent {
  type: "start";
  assessment_id: string;
  total_documents: number;
}

export interface DiscoveryDocumentStartEvent {
  type: "document_start";
  filename: string;
  index: number;
  total: number;
}

export interface DiscoveryDocumentResultEvent {
  type: "document_result";
  filename: string;
  extractor: string;
  nodes_found: number;
  edges_found: number;
  confidence: number;
  warnings: string[];
}

export interface DiscoveryMergingEvent {
  type: "merging";
  message: string;
}

export interface DiscoveryCsvGeneratedEvent {
  type: "csv_generated";
  node_count: number;
  edge_count: number;
  nodes_csv: string;
  edges_csv: string;
}

export interface DiscoveryPersistingEvent {
  type: "persisting";
  message: string;
}

export interface DiscoveryCompleteEvent {
  type: "complete";
  assessment_id: string;
  status: "graph_updated" | "no_data_extracted";
  node_count: number;
  edge_count: number;
  graph_status: string;
  warnings: string[];
  extraction_report: {
    per_document: Array<{
      filename: string;
      extractor: string;
      nodes_found: number;
      edges_found: number;
      confidence: number;
    }>;
    overall_confidence: number;
  };
}

export interface DiscoveryErrorEvent {
  type: "error";
  message: string;
}

export type DiscoveryEvent =
  | DiscoveryStartEvent
  | DiscoveryDocumentStartEvent
  | DiscoveryDocumentResultEvent
  | DiscoveryMergingEvent
  | DiscoveryCsvGeneratedEvent
  | DiscoveryPersistingEvent
  | DiscoveryCompleteEvent
  | DiscoveryErrorEvent;

// ---------------------------------------------------------------------------
// Simulation Result (/api/v1/assessments/{id}/simulate)
// ---------------------------------------------------------------------------

export interface SimulateRequest {
  target_id: string;
  already_migrated?: string[];
}

export interface SimulationResultResponse {
  assessment_id: string;
  target_id: string;
  impacted_services: ServiceNode[];
  critical_paths: string[][];
  revenue_at_risk: number;
  total_hosting_cost: number;
  potential_savings: number;
  monte_carlo: MonteCarloResult;
}

// ---------------------------------------------------------------------------
// Agent Runs (/api/v1/assessments/{id}/agent-runs)
// ---------------------------------------------------------------------------

export interface AgentRunResponse {
  agent_run_id: string;
  assessment_id: string;
  agent_name: string;
  status: string;
  started_at: string;
  completed_at?: string | null;
  summary?: unknown;
}

// Extra state the 12-agent Master Orchestrator pipeline
// (run_full_assessment_stream) computes beyond waves/decoupling_strategies/
// risk_assessment - persisted on the terminal AgentRun row's
// `pipeline_metrics` column (see backend/app/entities/agent_run.py) and
// surfaced here so the Planner page can show it without re-running anything.
// Absent/undefined for a run produced by the legacy 4-agent run_planner()
// path, which never populates this state.
export interface ComplexityMetrics {
  complexity_score: number;
  dimension_scores: {
    architecture: number;
    business: number;
    technology: number;
    integration: number;
    migration: number;
  };
  engineering_effort_days: number;
  estimated_timeline_weeks: number;
  team_size: number;
}

export interface EnterpriseRiskMetrics {
  risk_score: number;
  category_scores: Record<string, number>;
  top_risks: string[];
  mitigation_strategies: string[];
}

export interface CloudReadinessMetrics {
  readiness_score: number;
  platform_scores: Record<string, number>;
  recommended_platform: string;
}

export interface SimulationScenario {
  risk: number;
  duration_days: number;
  cost_usd: number;
  engineering_effort_days: number;
  business_impact_usd: number;
  cloud_readiness: number;
  confidence: number;
}

export interface SimulationMetrics {
  scenarios: Record<string, SimulationScenario>;
  force_all_strategies: boolean;
}

export interface RecommendationMetrics {
  recommended_strategy: string;
  engineering_recommendation: string;
  business_recommendation: string;
  modernization_recommendation: string;
  customer_recommendation: string;
  confidence_score: number;
}

export interface ExplainabilityMetrics {
  evidence: string[];
  dependencies_considered: string[];
  risks_considered: string[];
  confidence_explanation: string;
}

export interface PipelineMetrics {
  complexity?: ComplexityMetrics;
  enterprise_risk?: EnterpriseRiskMetrics;
  cloud_readiness?: CloudReadinessMetrics;
  simulation_results?: SimulationMetrics;
  recommendation?: RecommendationMetrics;
  explainability?: ExplainabilityMetrics;
  confidence_score?: number;
}

export interface RunPlannerResponse extends PipelineMetrics {
  assessment_id: string;
  waves: string[][];
  decoupling_strategies: DecouplingStrategy[];
  risk_assessment: Record<string, RiskAssessmentEntry>;
  agent_runs: AgentRunResponse[];
}

// ---------------------------------------------------------------------------
// Planner streaming (/api/v1/assessments/{id}/agent-runs/stream)
//
// Mirrors backend/app/services_v1/agent_run_service.py's run_planner_stream()
// event dicts 1:1 - each Server-Sent Event's `data:` line is exactly one of
// these, discriminated on `type`.
// ---------------------------------------------------------------------------

export interface PlannerStartEvent {
  type: "start";
  assessment_id: string;
}

export interface PlannerAgentResultEvent extends AgentRunResponse {
  type: "agent_result";
}

export interface PlannerCompleteEvent extends PipelineMetrics {
  type: "complete";
  assessment_id: string;
  waves: string[][];
  decoupling_strategies: DecouplingStrategy[];
  risk_assessment: Record<string, RiskAssessmentEntry>;
}

export interface PlannerErrorEvent {
  type: "error";
  message: string;
}

export type PlannerStreamEvent =
  | PlannerStartEvent
  | PlannerAgentResultEvent
  | PlannerCompleteEvent
  | PlannerErrorEvent;

// ---------------------------------------------------------------------------
// Structured agent output (best-effort parse of AgentRunResponse.summary.message
// for the Explainability view) - the underlying LLM call is prompted to return
// this shape as JSON, but it's never schema-enforced: the deterministic
// no-provider-configured fallback returns plain prose instead. Every field is
// optional and callers must treat a failed parse as "render the raw text".
// ---------------------------------------------------------------------------

export interface SharedDatabaseFinding {
  database_id: string;
  accessed_by: string[];
}

export interface DiscoveryAgentOutput {
  summary?: string;
  orphans_found?: string[];
  shared_databases?: SharedDatabaseFinding[];
  agent_log?: string;
}

export interface DependencyDecouplingStrategy {
  cycle: string[];
  description: string;
  recommendation: string;
}

export interface DependencyAgentOutput {
  cycles_detected_count?: number;
  decoupling_strategies?: DependencyDecouplingStrategy[];
  agent_log?: string;
}

export interface RiskAssessmentEntry {
  score: number;
  violations: string[];
  complexity: string;
}

export interface RiskAgentOutput {
  risk_threshold_exceeded?: boolean;
  objections?: string[];
  risk_assessment?: Record<string, RiskAssessmentEntry>;
  agent_log?: string;
}

export interface PlannerAgentOutput {
  waves?: string[][];
  adjustments_made?: string[];
  agent_log?: string;
}

export interface RecommendationAgentOutput {
  recommended_strategy?: string;
  engineering_recommendation?: string;
  business_recommendation?: string;
  modernization_recommendation?: string;
  customer_recommendation?: string;
  confidence_score?: number;
  agent_log?: string;
}

export interface ReportGenerationAgentOutput {
  executive_summary?: string;
  key_takeaways?: string[];
  agent_log?: string;
}

// The seven agent types below only appear in the 12-agent Master Orchestrator
// pipeline (run_planner_stream) - see backend/app/agents/MASTER_ORCHESTRATOR.md.
// Shapes mirror each agent's system prompt contract 1:1 (backend/app/agents/
// prompts.py) - every field optional since the LLM's JSON output is never
// schema-enforced (a failed parse just falls back to RawMessage).

export interface DigitalTwinAgentOutput {
  topology_summary?: string;
  node_type_breakdown?: Record<string, number>;
  highlights?: string[];
  agent_log?: string;
}

export interface MigrationGraphAgentOutput {
  graph_summary?: string;
  entity_counts?: Record<string, number>;
  key_relationships?: string[];
  agent_log?: string;
}

export interface ComplexityAgentOutput {
  complexity_score?: number;
  dimension_scores?: Record<string, number>;
  engineering_effort_days?: number;
  estimated_timeline_weeks?: number;
  team_size?: number;
  agent_log?: string;
}

export interface EnterpriseRiskAgentOutput {
  risk_score?: number;
  category_scores?: Record<string, number>;
  top_risks?: string[];
  mitigation_strategies?: string[];
  agent_log?: string;
}

export interface CloudReadinessAgentOutput {
  readiness_score?: number;
  platform_scores?: Record<string, number>;
  recommended_platform?: string;
  rationale?: string;
  agent_log?: string;
}

export interface SimulationScenarioOutput {
  risk: number;
  duration_days: number;
  cost_usd: number;
  confidence: number;
}

export interface SimulationAgentOutput {
  scenarios?: Record<string, SimulationScenarioOutput>;
  comparison_summary?: string;
  agent_log?: string;
}

export interface ExplainabilityAgentOutput {
  evidence?: string[];
  dependencies_considered?: string[];
  risks_considered?: string[];
  confidence_explanation?: string;
  agent_log?: string;
}

// ---------------------------------------------------------------------------
// Report Snapshot (/api/v1/assessments/{id}/report, .../report/feedback,
// .../migration-plan)
// ---------------------------------------------------------------------------

export interface ReportFeedbackRequest {
  rating: "up" | "down";
  comment?: string | null;
}

export interface FinalMigrationPlan {
  strategy: string;
}

export type ReportSection = "executive_summary" | "risk_summary" | "migration_waves" | "recommendations";

export interface ReportResponse {
  assessment_id: string;
  executive_summary: string;
  readiness_score: number;
  risk_summary?: unknown;
  migration_waves?: unknown;
  recommendations?: string[];
  generated_at: string;
  current_version: number;
  feedback_rating?: "up" | "down" | null;
  feedback_comment?: string | null;
  feedback_submitted_at?: string | null;
  final_migration_plan?: FinalMigrationPlan | null;
  final_plan_generated_at?: string | null;
}

export interface ReportReviseRequest {
  feedback: string;
}

export interface ReviseReportResponse extends ReportResponse {
  changed_sections: ReportSection[];
}

export interface ReportRevisionSummary {
  version: number;
  source: "generate" | "feedback";
  changed_sections?: ReportSection[] | null;
  feedback_comment?: string | null;
  created_at: string;
}

export interface ReportRevisionDetail extends ReportRevisionSummary {
  executive_summary: string;
  readiness_score: number;
  risk_summary?: unknown;
  migration_waves?: unknown;
  recommendations?: string[];
}

// ---------------------------------------------------------------------------
// Assessment Chat (/api/v1/assessments/{id}/chat) - document-grounded (RAG),
// distinct from the legacy global ChatMessage/ChatResponse above.
// ---------------------------------------------------------------------------

export interface AssessmentChatResponse {
  reply: string;
  trace_id?: string | null;
  // Upload IDs whose document chunks were actually retrieved and used to
  // ground this reply - empty if nothing relevant was found or discovered yet.
  sources: string[];
}
