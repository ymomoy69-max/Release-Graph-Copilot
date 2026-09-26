import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function Releases({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.releases>> | null>(null);

  useEffect(() => {
    api.releases(projectId).then(setRows);
  }, [projectId]);

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Releases</h2>
          <p className="muted">
            A release is a version we shipped (or tried to). Click a version to see services, commits, CI, and risk.
          </p>
        </div>
      </div>
      <div className="guide">
        <h3>How to read this table</h3>
        <ul>
          <li><strong>Status</strong> — DRAFT / DEPLOYED / ROLLED_BACK. DEPLOYED means it is in production in this demo.</li>
          <li><strong>Risk</strong> — LOW / MEDIUM / HIGH from a formula (services changed, production, incidents), not from an LLM.</li>
          <li><strong>Services</strong> — microservices included in that version (from the database, not a hardcoded list).</li>
        </ul>
      </div>
      <div className="card">
        {!rows ? (
          <div className="skeleton" style={{ height: 120 }} />
        ) : rows.length === 0 ? (
          <div className="empty">No releases stored for this project yet.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Version</th><th>Status</th><th>Risk</th><th>Services</th><th>Commits</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/releases/${r.id}`}>{r.version}</Link></td>
                    <td><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></td>
                    <td><span className={`badge ${r.risk_level.toLowerCase()}`}>{r.risk_level}</span></td>
                    <td>
                      <div className="pill-list">
                        {r.services.slice(0, 4).map((s) => <span key={s} className="pill">{s}</span>)}
                      </div>
                    </td>
                    <td>{r.commits_count}</td>
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
