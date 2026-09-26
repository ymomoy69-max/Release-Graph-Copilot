import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import DeployGateBanner from "../components/DeployGateBanner";

export default function ReleaseDetail() {
  const { id } = useParams();
  const [r, setR] = useState<Awaited<ReturnType<typeof api.release>> | null>(null);
  const [msg, setMsg] = useState("");

  function reload() {
    if (id) api.release(Number(id)).then(setR);
  }

  useEffect(() => {
    reload();
  }, [id]);

  async function rollback() {
    if (!id || !r?.baseline_version) return;
    const ok = window.confirm(
      `Roll production back to ${r.baseline_version}? ${r.version} will be marked rolled back.`,
    );
    if (!ok) return;
    try {
      const res = await api.rollback(Number(id));
      setMsg(`Production is now ${res.production_version}.`);
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Rollback failed");
    }
  }

  async function markReady() {
    if (!id) return;
    try {
      await api.markReleaseReady(Number(id));
      setMsg("Release marked READY. Deploy when the workspace scanner is clean.");
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not mark ready");
    }
  }

  async function deploy() {
    if (!id) return;
    let preview = { release_services: r?.services || [], affected_services: r?.services || [] };
    try {
      preview = await api.deployPreview(Number(id));
    } catch {
      /* still confirm with release services only */
    }
    const ok = window.confirm(
      `Deploy ${r?.version} to production?\n\nIn this release: ${preview.release_services.join(", ") || "—"}\n\nMay feel it (blast radius): ${preview.affected_services.join(", ") || "—"}`,
    );
    if (!ok) return;
    try {
      const res = await api.deployRelease(Number(id));
      setMsg(
        res.previous_production_version
          ? `Deployed ${res.version}. Previous production was ${res.previous_production_version}.`
          : `Deployed ${res.version} to production.`,
      );
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Deploy failed");
    }
  }

  if (!r) return <p className="muted">Loading release…</p>;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="muted">
            <Link to="/releases">Releases</Link> / {r.version}
            {r.is_production ? " · live in production" : ""}
          </p>
          <h2>Release {r.version}</h2>
          <p className="muted">{r.summary}</p>
          {r.baseline_version && (
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Baseline for rollback:{" "}
              {r.baseline_release_id ? (
                <Link to={`/releases/${r.baseline_release_id}`}>{r.baseline_version}</Link>
              ) : (
                r.baseline_version
              )}
            </p>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {r.can_mark_ready && (
            <button type="button" className="secondary" onClick={markReady}>
              Mark READY
            </button>
          )}
          {r.can_deploy && (
            <button type="button" className="primary" onClick={deploy}>
              Deploy to production
            </button>
          )}
          {r.deploy_blocked && !r.is_production && (
            <span className="badge high">Deploy blocked by scanner</span>
          )}
          {r.can_rollback && (
            <button type="button" className="danger" onClick={rollback}>
              Roll back to {r.baseline_version}
            </button>
          )}
        </div>
      </div>
      <div className="guide">
        <h3>What this page is</h3>
        <p className="muted" style={{ margin: 0 }}>
          Shipping record for one version. Risk factors come from the deterministic engine (services,
          incidents, production target). Rollback restores the linked baseline — not a label change only.
        </p>
      </div>
      <DeployGateBanner gate={r.deploy_gate} />
      {msg && <p className={msg.includes("failed") || msg.includes("blocked") ? "error" : "ok"}>{msg}</p>}
      <div className="grid">
        <div className="card stat">
          <div className="label">Status</div>
          <div className="value">
            <span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span>
          </div>
        </div>
        <div className="card stat">
          <div className="label">Environment</div>
          <div className="value" style={{ fontSize: "1.2rem" }}>
            {r.environment || "—"}
          </div>
        </div>
        <div className="card stat">
          <div className="label">Risk</div>
          <div className="value">
            <span className={`badge ${r.risk_level.toLowerCase()}`}>{r.risk_level}</span>
          </div>
          <div className="hint">Score {r.risk_score}</div>
        </div>
        <div className="card stat">
          <div className="label">Changes</div>
          <div className="value" style={{ fontSize: "1.2rem" }}>
            {r.commits_count} / {r.prs_count}
          </div>
          <div className="hint">Commits / pull requests</div>
        </div>
      </div>
      <div className="card">
        <h3>Services in this release</h3>
        <div className="pill-list" style={{ marginTop: 8 }}>
          {(r.services || []).map((s) => (
            <span key={s} className="pill">
              {s}
            </span>
          ))}
        </div>
      </div>
      {(r.commits_since_baseline || []).length > 0 && (
        <div className="card">
          <h3>Commits since baseline {r.baseline_version}</h3>
          {(r.commits_since_baseline || []).map((c) => (
            <div className="commit-row" key={c.sha}>
              <code>{c.sha}</code>
              <span>{c.message}</span>
              <span className="muted"> · {c.author}</span>
            </div>
          ))}
        </div>
      )}
      {(r.commits || []).length > 0 && (
        <div className="card">
          <h3>All commits on this release</h3>
          {(r.commits || []).map((c) => (
            <div className="commit-row" key={c.sha}>
              <code>{c.sha}</code>
              <span>{c.message}</span>
            </div>
          ))}
        </div>
      )}
      {(r.builds || []).length > 0 && (
        <div className="card">
          <h3>CI</h3>
          {(r.builds || []).map((b) => (
            <p key={b.id} className="muted">
              Build <span className={`badge ${b.status}`}>{b.status}</span> · {b.duration_seconds}s
            </p>
          ))}
          {(r.tests || []).map((t) => (
            <p key={t.suite} className="muted">
              {t.suite}: <span className={`badge ${t.status}`}>{t.status}</span> · {t.passed} passed /{" "}
              {t.failed} failed
            </p>
          ))}
        </div>
      )}
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
