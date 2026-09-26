import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AnalysisPayload, type DeployGate, type Project, type ReadinessPreset, type ReleaseTrain } from "../api";
import { notifyGraphRefresh } from "../graphRefresh";
import DeployGateBanner from "../components/DeployGateBanner";
import AnalysisList from "./AnalysisList";

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

function applyPreset(preset: ReadinessPreset) {
  return {
    workspace: preset.workspace,
    config: preset.org_config || "",
    ciDir: preset.ci_dir || "",
    repos: (preset.repos || []).join(", "),
  };
}

function presetForProject(project: Project): ReadinessPreset | null {
  const presets = project.readiness_presets || [];
  if (!presets.length) return null;
  const ws = (project.workspace_path || "").trim();
  const match = presets.find((p) => p.workspace === ws);
  return match || presets[0];
}

export default function ReadinessPage({
  project,
}: {
  project: Project;
  onProject: (id: number) => void;
}) {
  const presets = project.readiness_presets || [];
  const [presetId, setPresetId] = useState("");
  const [workspace, setWorkspace] = useState(project.workspace_path || "");
  const [config, setConfig] = useState(project.org_config_path || "");
  const [repos, setRepos] = useState("");
  const [ciDir, setCiDir] = useState("");
  const [changedPaths, setChangedPaths] = useState("");
  const [result, setResult] = useState<Checklist | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [scanSummary, setScanSummary] = useState("");
  const [ready, setReady] = useState<boolean | null>(null);
  const [deployGate, setDeployGate] = useState<DeployGate | null>(null);
  const [train, setTrain] = useState<ReleaseTrain | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [trainMsg, setTrainMsg] = useState("");

  useEffect(() => {
    const initial = presetForProject(project);
    if (initial) {
      setPresetId(initial.id);
      const fields = applyPreset(initial);
      setWorkspace(fields.workspace);
      setConfig(fields.config || project.org_config_path || "");
      setCiDir(fields.ciDir);
      setRepos(fields.repos);
    } else {
      setPresetId("");
      setWorkspace(project.workspace_path || "");
      setConfig(project.org_config_path || "");
      setRepos("");
      setCiDir("");
    }
    setResult(null);
    setAnalysis(null);
    setScanSummary("");
    setReady(null);
    setDeployGate(null);
    setError("");
  }, [project.id, project.workspace_path, project.org_config_path, project.readiness_presets]);

  function selectPreset(id: string) {
    setPresetId(id);
    const preset = presets.find((p) => p.id === id);
    if (!preset) return;
    const fields = applyPreset(preset);
    setWorkspace(fields.workspace);
    setConfig(fields.config);
    setCiDir(fields.ciDir);
    setRepos(fields.repos);
  }

  const activeHint = presets.find((p) => p.id === presetId)?.hint;

  async function runScan() {
    setLoading(true);
    setError("");
    setTrainMsg("");
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
      setDeployGate(res.deploy_gate || null);
      setTrain(res.release_train || null);
      if (res.org_config_path) setConfig(res.org_config_path);
      const n = res.scan?.services?.length || 0;
      const e = res.scan?.dependencies?.length || 0;
      const issues = res.analysis?.issue_count ?? res.scan?.issues?.length ?? 0;
      setScanSummary(
        `${n} services, ${e} connections, ${issues} scanner issue(s) from ${res.scan?.workspace || workspace}`,
      );
      notifyGraphRefresh({ projectId: project.id, reason: "readiness_check" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setLoading(false);
    }
  }

  async function startNextRelease() {
    setTrainMsg("");
    try {
      const rel = await api.startNextRelease(project.id);
      setTrainMsg(`Started draft release ${rel.version}.`);
      const t = await api.releaseTrain(project.id);
      setTrain(t);
      notifyGraphRefresh({ projectId: project.id, reason: "release_train" });
    } catch (e) {
      setTrainMsg(e instanceof Error ? e.message : "Could not start release");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Release readiness</h2>
          <p className="muted">
            Pick a workspace folder (or use the project preset), scan on disk, then run GO/NO-GO when org.yaml is
            set. Results update the graph, incidents, and Fix PRs.
          </p>
        </div>
      </div>

      <div className="card">
        <h3>Scan a workspace</h3>
        {presets.length > 0 && (
          <>
            <label>Workspace preset</label>
            <select
              className="project-select"
              value={presetId}
              onChange={(e) => selectPreset(e.target.value)}
              style={{ marginBottom: 12, maxWidth: "100%" }}
            >
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            {activeHint && <p className="muted" style={{ marginTop: 0 }}>{activeHint}</p>}
          </>
        )}
        <p className="muted">
          Absolute path to the repo (or a services folder). The scanner walks the tree on disk.
        </p>
        <label>Workspace folder</label>
        <input
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          placeholder="/path/to/your/microservices"
        />
        <button type="button" onClick={runScan} disabled={loading || !workspace.trim()} style={{ marginTop: 14 }}>
          {loading ? "Scanning…" : "Scan workspace & sync"}
        </button>
        {scanSummary && <p className="ok" style={{ marginTop: 10 }}>{scanSummary}</p>}
        <DeployGateBanner gate={deployGate} />
        {train && (
          <div className="card" style={{ marginTop: 12 }}>
            <p className="muted" style={{ marginTop: 0 }}>
              Production: <strong>{train.production_version || "—"}</strong>
              {train.draft_version ? ` · Draft: ${train.draft_version} (${train.draft_status})` : ""}
            </p>
            {train.can_start_next && !deployGate?.blocked && (
              <button type="button" className="secondary" onClick={startNextRelease}>
                Start next release
              </button>
            )}
            {trainMsg && <p className="ok">{trainMsg}</p>}
            <p style={{ marginBottom: 0 }}>
              <Link to="/releases">Open Releases</Link>
            </p>
          </div>
        )}
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

      <details className="card">
        <summary>
          <strong>GO / NO-GO with org.yaml</strong>
          <span className="muted"> — optional rgc checkers on the same workspace path</span>
        </summary>
        <p className="muted">
          Uses the workspace folder above. Choosing an RGC fixtures preset fills org.yaml, CI status dir, and repos.
          The scan button runs the full checker suite when org config is set.
        </p>
        <label>Org config (YAML file)</label>
        <input value={config} onChange={(e) => setConfig(e.target.value)} placeholder="optional org.yaml" />
        <label>Repos (comma-separated, or leave blank to auto-detect folders)</label>
        <input value={repos} onChange={(e) => setRepos(e.target.value)} />
        <label>CI status directory</label>
        <input value={ciDir} onChange={(e) => setCiDir(e.target.value)} />
        <label>Changed file paths</label>
        <input value={changedPaths} onChange={(e) => setChangedPaths(e.target.value)} />
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
