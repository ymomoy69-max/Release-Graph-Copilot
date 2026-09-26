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
  environment?: string | null;
  commits?: { sha: string; message: string; author: string }[];
  pull_requests?: { number: number; title: string }[];
  builds?: { id: number; status: string; duration_seconds: number | null }[];
  tests?: { suite: string; status: string; passed: number; failed: number }[];
  risk_factors?: { factor: string; weight: number; detail: string }[];
};

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<{ email: string; full_name: string; role: string }>("/auth/me"),
  projects: () =>
    request<{ id: number; slug: string; name: string; description: string; workspace_path?: string }[]>("/projects"),
  services: (projectId: number) =>
    request<{ id: number; name: string; criticality: string; source_path: string }[]>(
      `/services?project_id=${projectId}`,
    ),
  dashboard: (projectId: number) =>
    request<{
      active_releases: number;
      recent_releases: { id: number; version: string; status: string; risk: string }[];
      open_incidents: number;
      failed_builds: number;
      services_count: number;
      open_fix_prs?: number;
      copilot_insight: string;
    }>(`/dashboard?project_id=${projectId}`),
  releases: (projectId: number) => request<ReleaseSummary[]>(`/releases?project_id=${projectId}`),
  release: (id: number) => request<ReleaseSummary>(`/releases/${id}`),
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
    request(`/releases/${releaseId}/rollback`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  simulatePaymentFailure: (projectId: number) =>
    request<{ incident_id: number; message: string; service?: string }>(
      `/simulator/payment-failure?project_id=${projectId}`,
      { method: "POST" },
    ),
  simulateDeploy: (releaseId: number) =>
    request("/simulator/deploy", {
      method: "POST",
      body: JSON.stringify({ release_id: releaseId, environment_slug: "production" }),
    }),
  readinessPresets: () => request<{ id: string; label: string; kind: string }[]>("/readiness/presets"),
  readinessCheck: (body: Record<string, unknown>) =>
    request<{
      checklist: Record<string, unknown>;
      ready_to_release: boolean;
      analysis?: AnalysisPayload | null;
      scan?: ScanPayload | null;
    }>("/readiness/check", {
      method: "POST",
      body: JSON.stringify(body),
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
