import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function Dashboard({ project }: { project: { id: number; name: string; workspace_path?: string } }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.dashboard>> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setData(null);
    api.dashboard(project.id).then(setData).catch((e) => setErr(e.message));
  }, [project.id]);

  if (err) return <p className="error">{err}</p>;
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
            {project.workspace_path ? ` · ${project.workspace_path}` : ""}. Counts come from the database.
          </p>
        </div>
      </div>

      <div className="guide">
        <h3>How this product is organized</h3>
        <div className="steps">
          <div className="step">
            <div className="n">1 · SCAN</div>
            <p className="muted" style={{ margin: 0 }}>
              Point Readiness at any workspace of connected microservices. The graph and analysis update from disk.
            </p>
          </div>
          <div className="step">
            <div className="n">2 · GRAPH</div>
            <p className="muted" style={{ margin: 0 }}>
              Who depends on whom. Red arrows are the link that breaks. The four cards under the map say what would change.
            </p>
          </div>
          <div className="step">
            <div className="n">3 · INCIDENTS</div>
            <p className="muted" style={{ margin: 0 }}>
              Production problems. Open a timeline, then ask Copilot — it names files, impact, and fixes.
            </p>
          </div>
          <div className="step">
            <div className="n">4 · FIX PRs</div>
            <p className="muted" style={{ margin: 0 }}>
              Engine findings become assigned demo tickets. A person approves; merge is a status only — no GitHub or Jira.
            </p>
          </div>
          <div className="step">
            <div className="n">5 · RELEASES</div>
            <p className="muted" style={{ margin: 0 }}>
              {latest
                ? `Latest version on record: ${latest.version} (${latest.status}, ${latest.risk} risk).`
                : "No release rows yet — they appear when you seed or simulate a deploy."}
            </p>
          </div>
        </div>
      </div>

      <div className="grid">
        <Link to="/releases" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Active releases</div>
          <div className="value">{data.active_releases}</div>
          <div className="hint">Click to open the release list</div>
        </Link>
        <Link to="/incidents" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Open incidents</div>
          <div className="value">{data.open_incidents}</div>
          <div className="hint">Problems still not resolved</div>
        </Link>
        <div className="card stat">
          <div className="label">Failed builds</div>
          <div className="value">{data.failed_builds}</div>
          <div className="hint">CI failures on record</div>
        </div>
        <Link to="/fix-prs" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Open fix PRs</div>
          <div className="value">{data.open_fix_prs ?? 0}</div>
          <div className="hint">Assigned tickets waiting on a human</div>
        </Link>
        <Link to="/graph" className="card stat" style={{ color: "inherit", textDecoration: "none" }}>
          <div className="label">Services</div>
          <div className="value">{data.services_count}</div>
          <div className="hint">Boxes on the dependency graph</div>
        </Link>
      </div>
      <div className="card">
        <h3>Latest note from the data</h3>
        <p style={{ margin: "0.4rem 0 0" }}>{data.copilot_insight}</p>
        <p className="muted" style={{ marginTop: 8 }}>
          Scan a workspace on <Link to="/readiness">Readiness</Link>, review assigned tickets on{" "}
          <Link to="/fix-prs">Fix PRs</Link>, or ask <Link to="/copilot">Copilot</Link> what is wrong.
        </p>
      </div>
      <div className="card">
        <h3>Recent releases</h3>
        {data.recent_releases.length === 0 ? (
          <div className="empty">No releases stored for this project yet.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Version</th><th>Shipped?</th><th>How risky</th></tr></thead>
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
