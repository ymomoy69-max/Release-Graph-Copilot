import { useEffect, useState } from "react";
import { api, type AnalysisPayload } from "../api";
import AnalysisList from "./AnalysisList";

type Preset = { id: string; label: string; kind: string };

type Checklist = {
  release_id: string;
  verdict: string;
  risk: string;
  gate: string;
  block_report?: string | null;
  note?: string;
  checks: {
    id: string;
    name: string;
    status: string;
    summary: string;
    findings: unknown[];
  }[];
  e2e?: { folders: string[]; estimate_display: string };
};

export default function ReadinessPage({
  project,
  onProject,
}: {
  project: { id: number; name: string; workspace_path?: string };
  onProject: (id: number) => void;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [workspace, setWorkspace] = useState(project.workspace_path || "");
  const [config, setConfig] = useState("");
  const [repos, setRepos] = useState("");
  const [ciDir, setCiDir] = useState("");
  const [changedPaths, setChangedPaths] = useState("");
  const [result, setResult] = useState<Checklist | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [scanSummary, setScanSummary] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.readinessPresets().then(setPresets).catch(() => {});
  }, []);

  useEffect(() => {
    if (project.workspace_path) setWorkspace(project.workspace_path);
  }, [project.workspace_path]);

  async function runScan() {
    setLoading(true);
    setError("");
    try {
      const res = await api.scanWorkspace(workspace, project.id);
      setAnalysis(res.analysis);
      const n = res.scan.services?.length || 0;
      const e = res.scan.dependencies?.length || 0;
      setScanSummary(`${n} services, ${e} connections from ${res.scan.workspace || workspace}`);
      setResult(null);
      setReady(null);
      if (res.project && res.project.id !== project.id) onProject(res.project.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }

  async function runPreset(id: string) {
    setLoading(true);
    setError("");
    try {
      const res = await api.readinessCheck({ preset: id, project_id: project.id });
      setResult(res.checklist as Checklist);
      setReady(res.ready_to_release);
      setAnalysis(res.analysis || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check failed");
    } finally {
      setLoading(false);
    }
  }

  async function runCustom() {
    setLoading(true);
    setError("");
    try {
      const res = await api.readinessCheck({
        workspace,
        project_id: project.id,
        config: config || undefined,
        repos: repos.split(",").map((r) => r.trim()).filter(Boolean),
        ci_dir: ciDir || undefined,
        changed_paths: changedPaths.split(",").map((p) => p.trim()).filter(Boolean),
      });
      setResult(res.checklist as Checklist);
      setReady(res.ready_to_release);
      setAnalysis(res.analysis || null);
      const n = res.scan?.services?.length || 0;
      setScanSummary(n ? `${n} services discovered` : scanSummary);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Check failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Release readiness</h2>
          <p className="muted">
            Point this at any folder of connected microservices. Checkers and the scanner name the
            file and blast radius first. Groq may rephrase that finding. Open tickets then appear on{" "}
            <strong>Fix PRs</strong> for a human to approve.
          </p>
        </div>
      </div>

      <div className="card">
        <h3>Scan a workspace</h3>
        <p className="muted">
          Absolute path to the repo (or a services folder). Example: this product’s{" "}
          <code>demo/ecommerce</code> directory, or any other org checkout.
        </p>
        <label>Workspace folder</label>
        <input
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          placeholder="/path/to/your/microservices"
        />
        <button type="button" onClick={runScan} disabled={loading || !workspace.trim()} style={{ marginTop: 14 }}>
          {loading ? "Scanning…" : "Scan workspace"}
        </button>
        {scanSummary && <p className="ok" style={{ marginTop: 10 }}>{scanSummary}</p>}
      </div>

      {analysis && (
        <>
          <div className="page-head" style={{ marginBottom: 8 }}>
            <h3>
              Analysis · {analysis.issue_count} issue{analysis.issue_count === 1 ? "" : "s"}
              {analysis.high_count ? ` · ${analysis.high_count} high` : ""}
            </h3>
          </div>
          <AnalysisList
            issues={analysis.issues}
            safety={analysis.safety}
            proposalsCreated={analysis.proposals_created}
          />
        </>
      )}

      <div className="card">
        <h3>Optional: rgc GO / NO-GO fixtures</h3>
        <p className="muted">Bundled demo checklists when you have org YAML. Skip if you only need the graph scan.</p>
        <div className="chip-row" style={{ marginTop: 10 }}>
          {presets.map((p) => (
            <button key={p.id} type="button" className="secondary" disabled={loading} onClick={() => runPreset(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <details className="card">
        <summary>
          <strong>Advanced: org YAML + named repos</strong>
          <span className="muted"> — only if your checkers need fixtures/org.yaml</span>
        </summary>
        <label>Org config (YAML file)</label>
        <input value={config} onChange={(e) => setConfig(e.target.value)} placeholder="optional org.yaml" />
        <label>Repos (comma-separated, or leave blank to auto-detect folders)</label>
        <input value={repos} onChange={(e) => setRepos(e.target.value)} />
        <label>CI status directory</label>
        <input value={ciDir} onChange={(e) => setCiDir(e.target.value)} />
        <label>Changed file paths</label>
        <input value={changedPaths} onChange={(e) => setChangedPaths(e.target.value)} />
        <button type="button" onClick={runCustom} disabled={loading || !workspace.trim()} style={{ marginTop: 14 }}>
          {loading ? "Running checks…" : "Run readiness check"}
        </button>
      </details>

      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <div className={`verdict-banner ${result.verdict === "go" ? "go" : "nogo"}`}>
            <div>
              <h3 style={{ color: "inherit" }}>{result.verdict === "go" ? "Ready to release" : "Not ready"}</h3>
              <p className="muted" style={{ margin: 0 }}>
                Risk {result.risk} · {result.release_id}
                {result.e2e ? ` · E2E ${result.e2e.estimate_display}` : ""}
              </p>
              {result.note && <p className="muted">{result.note}</p>}
            </div>
            <span className={`badge ${result.verdict === "go" ? "go" : "high"}`}>
              {result.verdict.toUpperCase()}
            </span>
          </div>
          {result.block_report && (
            <>
              <p className="muted">Why it is blocked, and what the engine suggests:</p>
              <pre className="snippet">{result.block_report}</pre>
            </>
          )}
          {result.checks.map((c) => (
            <div key={c.id} className={`card check-card ${c.status}`}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <strong>{c.name}</strong>
                <span className={`badge ${c.status}`}>{c.status}</span>
              </div>
              <div className="muted" style={{ marginTop: 6 }}>{c.summary}</div>
            </div>
          ))}
        </>
      )}

      {ready === true && (
        <p className="ok">Blocking checks passed. Human approval is still required before an E2E trigger.</p>
      )}
    </>
  );
}
