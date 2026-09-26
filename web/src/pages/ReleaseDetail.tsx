import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";

export default function ReleaseDetail() {
  const { id } = useParams();
  const [r, setR] = useState<Awaited<ReturnType<typeof api.release>> | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (id) api.release(Number(id)).then(setR);
  }, [id]);

  async function rollback() {
    if (!id || !window.confirm("Confirm rollback? This requires explicit human approval.")) return;
    try {
      await api.rollback(Number(id));
      setMsg("Rollback recorded in the audit log.");
      api.release(Number(id)).then(setR);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Rollback failed");
    }
  }

  if (!r) return <p className="muted">Loading release…</p>;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="muted"><Link to="/releases">Releases</Link> / {r.version}</p>
          <h2>Release {r.version}</h2>
          <p className="muted">{r.summary}</p>
        </div>
        {r.rollback_available && r.status !== "ROLLED_BACK" && (
          <button className="danger" onClick={rollback}>Undo this deploy (rollback)</button>
        )}
      </div>
      <div className="guide">
        <h3>What this page is</h3>
        <p className="muted" style={{ margin: 0 }}>
          This is the shipping record for one version. <strong>Risk factors</strong> below are the
          reasons the engine scored it MEDIUM or HIGH. Rollback asks you to confirm — Copilot cannot
          roll back by itself.
        </p>
      </div>
      {msg && <p className={msg.includes("failed") ? "error" : "ok"}>{msg}</p>}
      <div className="grid">
        <div className="card stat">
          <div className="label">Status</div>
          <div className="value"><span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span></div>
        </div>
        <div className="card stat">
          <div className="label">Environment</div>
          <div className="value" style={{ fontSize: "1.2rem" }}>{r.environment || "—"}</div>
        </div>
        <div className="card stat">
          <div className="label">Risk</div>
          <div className="value"><span className={`badge ${r.risk_level.toLowerCase()}`}>{r.risk_level}</span></div>
          <div className="hint">Score {r.risk_score}</div>
        </div>
        <div className="card stat">
          <div className="label">Changes</div>
          <div className="value" style={{ fontSize: "1.2rem" }}>{r.commits_count} / {r.prs_count}</div>
          <div className="hint">Commits / pull requests</div>
        </div>
      </div>
      <div className="card">
        <h3>Services in this release</h3>
        <div className="pill-list" style={{ marginTop: 8 }}>
          {(r.services || []).map((s) => <span key={s} className="pill">{s}</span>)}
        </div>
      </div>
      <div className="card">
        <h3>Commits</h3>
        {(r.commits || []).map((c) => (
          <div className="commit-row" key={c.sha}>
            <code>{c.sha}</code>
            <span>{c.message}</span>
          </div>
        ))}
      </div>
      <div className="card">
        <h3>CI</h3>
        {(r.builds || []).map((b) => (
          <p key={b.id} className="muted">Build <span className={`badge ${b.status}`}>{b.status}</span> · {b.duration_seconds}s</p>
        ))}
        {(r.tests || []).map((t) => (
          <p key={t.suite} className="muted">{t.suite}: <span className={`badge ${t.status}`}>{t.status}</span> · {t.passed} passed / {t.failed} failed</p>
        ))}
      </div>
      <div className="card">
        <h3>Risk factors (deterministic engine)</h3>
        <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem" }}>
          {(r.risk_factors || []).map((f) => (
            <li key={f.factor} style={{ marginBottom: 6 }}>
              {f.detail} <span className="muted">(weight {f.weight})</span>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
