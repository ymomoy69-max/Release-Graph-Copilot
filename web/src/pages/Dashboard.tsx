import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import DeployGateBanner from "../components/DeployGateBanner";
import { notifyGraphRefresh } from "../graphRefresh";

export default function Dashboard({ project }: { project: { id: number; name: string; workspace_path?: string } }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.dashboard>> | null>(null);
  const [err, setErr] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(() => {
    setRefreshing(true);
    return api
      .dashboard(project.id)
      .then(setData)
      .catch((e) => setErr(e.message))
      .finally(() => setRefreshing(false));
  }, [project.id]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 20_000);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  useEffect(() => {
    const handler = () => void load();
    window.addEventListener("rg:graph-refresh", handler);
    return () => window.removeEventListener("rg:graph-refresh", handler);
  }, [load]);

  if (err && !data) return <p className="error">{err}</p>;
  if (!data) {
    return (
      <>
        <div className="page-head"><div><h2>Home</h2></div></div>
        <div className="grid">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card"><div className="skeleton" style={{ height: 54 }} /></div>
          ))}
        </div>
      </>
    );
  }

  const latest = data.recent_releases[0];

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Home</h2>
          <p className="muted">
            Live snapshot of <strong>{project.name}</strong>
            {data.workspace_path ? ` · scanning ${data.workspace_path}` : project.workspace_path ? ` · ${project.workspace_path}` : ""}.
            {refreshing ? " Refreshing…" : ""}
          </p>
        </div>
        <button
          type="button"
          className="secondary"
          disabled={refreshing}
          onClick={() => {
            notifyGraphRefresh({ projectId: project.id, reason: "dashboard" });
            void load();
          }}
        >
          Refresh
        </button>
      </div>

      <div className="guide">
        <h3>IBM Bob workflow — what this app runs</h3>
        <p className="muted" style={{ margin: "0 0 0.8rem" }}>
          Bob built the engine. These eight steps are the same agentic loop on a sample org: scan, understand,
          risk, tests, review, readiness, fix, re-check.
        </p>
        <div className="steps">
          <div className="step">
            <div className="n">1 · ANALYZE</div>
            <p className="muted" style={{ margin: 0 }}>
              <Link to="/readiness">Readiness</Link> walks an unfamiliar workspace on disk.
            </p>
          </div>
          <div className="step">
            <div className="n">2 · GRAPH</div>
            <p className="muted" style={{ margin: 0 }}>
              <Link to="/graph">Release Graph</Link> — who depends on whom, blast radius, broken links.
            </p>
          </div>
          <div className="step">
            <div className="n">3 · RISK</div>
            <p className="muted" style={{ margin: 0 }}>
              Checkers + risk score. High findings block deploy.
            </p>
          </div>
          <div className="step">
            <div className="n">4 · TESTS</div>
            <p className="muted" style={{ margin: 0 }}>
              Playwright map vs deploy graph. Drift is a finding, not a guess.
            </p>
          </div>
          <div className="step">
            <div className="n">5 · REVIEW</div>
            <p className="muted" style={{ margin: 0 }}>
              <Link to="/releases">Releases</Link> and the deploy gate. Copilot only uses tools.
            </p>
          </div>
          <div className="step">
            <div className="n">6 · READY</div>
            <p className="muted" style={{ margin: 0 }}>
              GO/NO-GO checklist with citations. Human still holds the gate.
            </p>
          </div>
          <div className="step">
            <div className="n">7 · FIX</div>
            <p className="muted" style={{ margin: 0 }}>
              <Link to="/fix-prs">Fix PRs</Link> — file, line, engine fix. A person applies and approves.
            </p>
          </div>
          <div className="step">
            <div className="n">8 · RE-CHECK</div>
            <p className="muted" style={{ margin: 0 }}>
              Re-scan. Tickets close only if the finding is gone.
            </p>
          </div>
        </div>
      </div>

      {data.shop_status && (
        <div className="ops-strip card">
          <span>
            Scan: <strong>{data.scan_issue_count ?? 0}</strong> issue(s)
          </span>
          <span>
            Incidents: <strong>{data.open_incidents}</strong> open
          </span>
          <span>
            Fix PRs: <strong>{data.open_fix_prs ?? 0}</strong> open
          </span>
          <span>
            Shop payments:{" "}
            <strong>
              {data.shop_status.payment_status === "ok"
                ? "healthy"
                : data.shop_status.payment_status === "failure_on"
                  ? "failure mode ON"
                  : "unknown (shop down?)"}
            </strong>
          </span>
        </div>
      )}

      {data.production_risk_level && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>
            Production risk:{" "}
            <span className={`badge ${data.production_risk_level.toLowerCase()}`}>
              {data.production_risk_level}
            </span>
            {data.production_risk_score != null ? ` (score ${data.production_risk_score})` : ""}
          </h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Rescored from the live workspace scan on each Home refresh — not a static label.
          </p>
          {(data.production_risk_factors || []).length > 0 && (
            <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
              {data.production_risk_factors.map((f) => (
                <li key={f.factor}>
                  <strong>{f.factor}</strong> ({f.weight > 0 ? "+" : ""}{f.weight}): {f.detail}
                </li>
              ))}
            </ul>
          )}
          {data.production_release_id && (
            <p style={{ marginBottom: 0 }}>
              <Link to={`/releases/${data.production_release_id}`}>Open production release</Link>
            </p>
          )}
        </div>
      )}

      <div className="grid">
        <Link to="/releases" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Active releases</div>
          <div className="value">{data.active_releases}</div>
          <div className="hint">Click to open the release list</div>
        </Link>
        <Link to="/incidents" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Open incidents</div>
          <div className="value">{data.open_incidents}</div>
          <div className="hint">From scan + live checkout</div>
        </Link>
        <div className="card stat">
          <div className="label">Scanner issues (live)</div>
          <div className="value">{data.scan_issue_count ?? 0}</div>
          <div className="hint">
            {(data.scan_high_count ?? 0) > 0 ? `${data.scan_high_count} high severity` : "On disk now"}
          </div>
        </div>
        <Link to="/fix-prs" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Open fix PRs</div>
          <div className="value">{data.open_fix_prs ?? 0}</div>
          <div className="hint">Assigned tickets waiting on a human</div>
        </Link>
        <Link to="/graph" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Breaking links</div>
          <div className="value">{data.broken_links ?? 0}</div>
          <div className="hint">{data.services_count} services mapped</div>
        </Link>
      </div>
      <DeployGateBanner gate={data.deploy_gate} />

      <div className="card">
        <h3>Latest from the workspace</h3>
        <p style={{ margin: "0.4rem 0 0" }}>{data.copilot_insight}</p>
        <p className="muted" style={{ marginTop: 8 }}>
          Scan on <Link to="/readiness">Readiness</Link>, review tickets on{" "}
          <Link to="/fix-prs">Fix PRs</Link>, or ask <Link to="/copilot">Copilot</Link> what is wrong.
        </p>
      </div>
      {(data.recent_audit || []).length > 0 && (
        <div className="card">
          <h3>Recent activity</h3>
          <ul className="timeline" style={{ margin: 0 }}>
            {data.recent_audit!.map((e) => (
              <li key={e.id}>
                <div className="muted">{new Date(e.timestamp).toLocaleString()}</div>
                <strong>{e.action}</strong>
                <span className="muted">
                  {" "}
                  · {e.entity_type} #{e.entity_id}
                  {e.user_email ? ` · ${e.user_email}` : ""}
                </span>
              </li>
            ))}
          </ul>
          <p style={{ marginBottom: 0 }}>
            <Link to="/audit">Full audit log</Link>
          </p>
        </div>
      )}

      <div className="card">
        <h3>Recent releases</h3>
        {data.recent_releases.length === 0 ? (
          <div className="empty">No releases stored for this project yet.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Status</th>
                  <th>Risk</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_releases.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/releases/${r.id}`}>{r.version}</Link></td>
                    <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                    <td><span className={`badge ${r.risk.toLowerCase()}`}>{r.risk}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
