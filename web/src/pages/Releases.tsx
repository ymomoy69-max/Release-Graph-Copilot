import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ReleaseTrain } from "../api";

export default function Releases({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.releases>> | null>(null);
  const [train, setTrain] = useState<ReleaseTrain | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    return Promise.all([api.releases(projectId), api.releaseTrain(projectId)]).then(([list, t]) => {
      setRows(list);
      setTrain(t);
    });
  }, [projectId]);

  useEffect(() => {
    load().catch((e) => setErr(e instanceof Error ? e.message : "Failed to load releases"));
  }, [load]);

  async function startNext() {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const created = await api.startNextRelease(projectId);
      setMsg(`Started ${created.version} from baseline ${created.baseline_version || "production"}.`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not start next release");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Releases</h2>
          <p className="muted">
            Production runs one version at a time. New work goes on the next release; rollback restores
            the previous production baseline.
          </p>
        </div>
        {train?.can_start_next && (
          <button type="button" className="primary" disabled={busy} onClick={startNext}>
            {busy ? "Starting…" : "Start next release"}
          </button>
        )}
      </div>

      {err && <p className="error">{err}</p>}
      {msg && <p className="ok">{msg}</p>}

      <div className="guide">
        <h3>Release train</h3>
        <ul>
          <li>
            <strong>Production</strong> —{" "}
            {train?.production_version
              ? `${train.production_version} (live)`
              : "Scan a workspace on Readiness to create the first baseline."}
          </li>
          <li>
            <strong>In progress</strong> —{" "}
            {train?.draft_version
              ? `${train.draft_version} (${train.draft_status}, baseline ${train.draft_baseline_version})`
              : "None — click Start next release when production is stable."}
          </li>
          <li>
            <strong>Deploy</strong> — blocked while critical scanner findings remain in the workspace.
          </li>
          <li>
            <strong>Rollback</strong> — on the live release only; production returns to its baseline version.
          </li>
        </ul>
      </div>

      <div className="card">
        {!rows ? (
          <div className="skeleton" style={{ height: 120 }} />
        ) : rows.length === 0 ? (
          <div className="empty">No releases yet. Scan a workspace on Readiness first.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Status</th>
                  <th>Risk</th>
                  <th>Baseline</th>
                  <th>Services</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/releases/${r.id}`}>{r.version}</Link>
                      {r.is_production ? <span className="pill" style={{ marginLeft: 8 }}>production</span> : null}
                    </td>
                    <td>
                      <span className={`badge ${r.status.toLowerCase()}`}>{r.status}</span>
                    </td>
                    <td>
                      <span className={`badge ${r.risk_level.toLowerCase()}`}>{r.risk_level}</span>
                    </td>
                    <td className="muted">{r.baseline_version || "—"}</td>
                    <td>
                      <div className="pill-list">
                        {r.services.slice(0, 4).map((s) => (
                          <span key={s} className="pill">
                            {s}
                          </span>
                        ))}
                      </div>
                    </td>
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
