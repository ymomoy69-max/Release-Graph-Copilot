const API = "/api/v1";

export function getToken(): string | null {
  return localStorage.getItem("rgc_token");
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem("rgc_token", token);
  else localStorage.removeItem("rgc_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const msg = err.message || err.detail || res.statusText;
    if (res.status === 0 || res.status >= 500) {
      throw new Error(`API unreachable (${res.status}). Start backend on port 8000.`);
    }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export type ReleaseSummary = {
  id: number;
  version: string;
  status: string;
  risk_level: string;
  risk_score: number;
  summary: string;
  services: string[];
  commits_count: number;
  prs_count: number;
  rollback_available?: boolean;
  baseline_release_id?: number | null;
  baseline_version?: string | null;
  is_production?: boolean;
  can_deploy?: boolean;
  can_mark_ready?: boolean;
  can_start_next?: boolean;
  can_rollback?: boolean;
  environment?: string | null;
  commits?: { sha: string; message: string; author: string }[];
  pull_requests?: { number: number; title: string }[];
  builds?: { id: number; status: string; duration_seconds: number | null }[];
  tests?: { suite: string; status: string; passed: number; failed: number }[];
  risk_factors?: { factor: string; weight: number; detail: string }[];
  commits_since_baseline?: { sha: string; message: string; author: string }[];
  deploy_blocked?: boolean;
  deploy_block_message?: string | null;
  deploy_gate?: DeployGate | null;
};

export type ReadinessPreset = {
  id: string;
  label: string;
  workspace: string;
  org_config?: string;
  ci_dir?: string;
  repos?: string[];
  hint?: string;
};

export type Project = {
  id: number;
  slug: string;
  name: string;
  description: string;
  workspace_path?: string;
  org_config_path?: string;
  readiness_presets?: ReadinessPreset[];
};

export type ReleaseTrain = {
  production_release_id: number | null;
  production_version: string | null;
  draft_release_id: number | null;
  draft_version: string | null;
  draft_status: string | null;
  draft_baseline_version: string | null;
  can_start_next: boolean;
};

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<{ email: string; full_name: string; role: string }>("/auth/me"),
  projects: () => request<Project[]>("/projects"),
  services: (projectId: number) =>
    request<{ id: number; name: string; criticality: string; source_path: string }[]>(
      `/services?project_id=${projectId}`,
    ),
  dashboard: (projectId: number) =>
    request<DashboardPayload>(`/dashboard?project_id=${projectId}`),
  releaseTrain: (projectId: number) =>
    request<ReleaseTrain>(`/release-train?project_id=${projectId}`),
  releases: (projectId: number) => request<ReleaseSummary[]>(`/releases?project_id=${projectId}`),
  release: (id: number) => request<ReleaseSummary>(`/releases/${id}`),
  startNextRelease: (projectId: number, summary?: string) =>
    request<ReleaseSummary>(`/releases/next?project_id=${projectId}`, {
      method: "POST",
      body: JSON.stringify({ summary: summary || null }),
    }),
  markReleaseReady: (releaseId: number) =>
    request<ReleaseSummary>(`/releases/${releaseId}/mark-ready`, { method: "POST" }),
  deployRelease: (releaseId: number) =>
    request<{ version: string; previous_production_version?: string | null }>(
      `/releases/${releaseId}/deploy`,
      { method: "POST", body: JSON.stringify({ confirm: true, environment_slug: "production" }) },
    ),
  deployPreview: (releaseId: number) =>
    request<{ release_services: string[]; affected_services: string[] }>(
      `/releases/${releaseId}/deploy-preview`,
    ),
  shopStatus: () => request<ShopStatus>("/shop-status"),
  syncShopIncidents: (projectId: number) =>
    request<ShopStatus & { ok: boolean }>(`/incidents/sync-shop?project_id=${projectId}`, {
      method: "POST",
    }),
  rescanVerifyFixPr: (id: number) =>
    request<FixPr & { scan?: { issues?: number; workspace?: string; error?: string } }>(
      `/fix-prs/${id}/rescan-verify`,
      { method: "POST" },
    ),
  graph: (projectId: number) =>
    request<GraphPayload>(`/graph?project_id=${projectId}`),
  copilotAsk: (projectId: number, question: string) =>
    request<{ answer: string; tool_calls: unknown[] }>("/copilot/ask", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, question }),
    }),
  incidents: (projectId: number) =>
    request<{
      id: number;
      title: string;
      status: string;
      severity: string;
      service_name: string | null;
      created_at: string;
    }[]>(`/incidents?project_id=${projectId}`),
  incident: (id: number) =>
    request<{
      id: number;
      title: string;
      status: string;
      service: string | null;
      release_id: number | null;
      timeline: { time: string; type: string; message: string }[];
    }>(`/incidents/${id}`),
  audit: () =>
    request<
      {
        id: number;
        timestamp: string;
        action: string;
        entity_type: string;
        entity_id: string | number;
        ai_generated: boolean;
        user_email: string | null;
      }[]
    >("/audit"),
  rollback: (releaseId: number) =>
    request<{ ok: boolean; production_version: string; rolled_back_version: string }>(
      `/releases/${releaseId}/rollback`,
      {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      },
    ),
  runCheckoutFailure: (projectId: number) =>
    request<{ incident_id: number; message: string; service?: string; http_status?: number; reused?: boolean }>(
      `/incidents/checkout-failure?project_id=${projectId}`,
      { method: "POST" },
    ),
  readinessCheck: (body: Record<string, unknown>) =>
    request<ReadinessResult>("/readiness/check", {
      method: "POST",
      body: JSON.stringify({ persist: true, ...body }),
    }),
  scanWorkspace: (workspace: string, projectId?: number) =>
    request<{
      project: { id: number; slug: string; name: string; workspace_path?: string } | null;
      scan: ScanPayload;
      analysis: AnalysisPayload | null;
    }>("/workspaces/scan", {
      method: "POST",
      body: JSON.stringify({ workspace, project_id: projectId, persist: true }),
    }),
  analyzeErrors: (projectId: number, extras?: { workspace?: string; incident_id?: number }) =>
    request<AnalysisPayload>("/analysis/errors", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, ...extras }),
    }),
  users: () => request<{ id: number; email: string; full_name: string; role: string }[]>("/users"),
  fixPrs: (projectId: number) => request<FixPr[]>(`/fix-prs?project_id=${projectId}`),
  assignFixPr: (id: number, assignee_user_id: number) =>
    request<FixPr>(`/fix-prs/${id}/assign`, {
      method: "PATCH",
      body: JSON.stringify({ assignee_user_id }),
    }),
  approveFixPr: (id: number) =>
    request<FixPr>(`/fix-prs/${id}/approve`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  rejectFixPr: (id: number) =>
    request<FixPr>(`/fix-prs/${id}/reject`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  mergeFixPr: (id: number) =>
    request<FixPr>(`/fix-prs/${id}/merge`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
};

export type DeployGate = {
  blocked: boolean;
  message?: string | null;
  blocking_count: number;
  issue_count: number;
  findings: {
    code: string;
    file: string;
    line?: number | null;
    service?: string;
    blocking: boolean;
    incident_id?: number | null;
  }[];
};

export type ShopStatus = {
  gateway_url: string;
  storefront_url: string;
  payment_failure_mode: boolean | null;
  payment_status: string;
};

export type DashboardPayload = {
  active_releases: number;
  recent_releases: { id: number; version: string; status: string; risk: string }[];
  open_incidents: number;
  failed_builds: number;
  services_count: number;
  open_fix_prs?: number;
  copilot_insight: string;
  workspace_path?: string | null;
  scan_issue_count?: number;
  scan_high_count?: number;
  broken_links?: number;
  production_version?: string | null;
  production_release_id?: number | null;
  draft_version?: string | null;
  production_risk_level?: string | null;
  production_risk_score?: number | null;
  production_risk_factors?: { factor: string; weight: number; detail: string }[];
  deploy_gate?: DeployGate | null;
  shop_status?: ShopStatus | null;
  recent_audit?: {
    id: number;
    timestamp: string;
    action: string;
    entity_type: string;
    entity_id: string | number;
    ai_generated: boolean;
    user_email: string | null;
  }[];
};

export type ReadinessResult = {
  checklist: Record<string, unknown>;
  ready_to_release: boolean;
  analysis?: AnalysisPayload | null;
  scan?: ScanPayload | null;
  deploy_gate?: DeployGate | null;
  release_train?: ReleaseTrain | null;
  org_config_path?: string | null;
};

export type ScanPayload = {
  workspace?: string;
  name?: string;
  services?: { name: string; path: string; criticality: string }[];
  dependencies?: { from: string; to: string; evidence: string }[];
  issues?: unknown[];
  repo_folders?: string[];
  error?: string;
};

export type AnalysisIssue = {
  file: string;
  line?: number | null;
  service?: string | null;
  severity: string;
  problem: string;
  affects: string[];
  consequences: string;
  fix: string;
  engine_fix?: string;
  llm_fix?: string;
  evidence?: string | null;
  source: string;
  code?: string;
  verification?: string;
  human_required?: boolean;
  llm_accepted?: boolean;
  confidence?: string;
};

export type AnalysisPayload = {
  project_id: number;
  workspace?: string | null;
  issue_count: number;
  high_count: number;
  services: string[];
  issues: AnalysisIssue[];
  safety?: {
    engine_source_of_truth?: boolean;
    human_required?: boolean;
    llm_used?: boolean;
    llm_accepted?: number;
    llm_rejected?: number;
    llm_enabled?: boolean;
    note?: string;
  };
  proposals_created?: number;
  proposals?: FixPr[];
};

export type FixPr = {
  id: number;
  number: number;
  title: string;
  body: string;
  status: string;
  assignee: { id: number; email: string; full_name: string; role: string } | null;
  reviewed_by: { id: number; email: string; full_name: string } | null;
  file: string;
  line?: number | null;
  service?: string | null;
  severity: string;
  code: string;
  engine_fix: string;
  llm_suggestion?: string | null;
  evidence?: string | null;
  affects: string[];
  confidence: string;
  llm_accepted: boolean;
  human_required: boolean;
  verify?: string;
  verify_message?: string | null;
};

export type GraphNode = {
  id: string;
  label: string;
  type: string;
  status?: string;
  rank?: number;
  headline?: string;
  wrong?: string;
  if_breaks?: string;
  would_change?: string;
  issue_count?: number;
  file?: string | null;
  line?: number | null;
  affects?: string[];
  updated?: { service: string; version?: string; functionality: string; also?: string[] } | null;
  incident?: string | null;
  scan_incident_id?: number | null;
  scan_incidents?: { incident_id: number; title: string; code: string; file: string }[];
};

export type GraphPayload = {
  nodes: GraphNode[];
  edges: { id: string; source: string; target: string; broken?: boolean; label?: string }[];
  summary: string;
  broken_links: {
    from: string;
    to: string;
    why: string;
    if_breaks: string;
    would_change: string;
    affects: string[];
  }[];
  updates: { service: string; version?: string; functionality: string; also?: string[] }[];
  broken_services: string[];
  affected_services: string[];
  workspace?: string | null;
};
