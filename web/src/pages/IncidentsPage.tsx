import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AnalysisPayload } from "../api";
import AnalysisList from "./AnalysisList";

const EVENT_TITLE: Record<string, string> = {
  deployment_completed: "A release went to production",
  metric_spike: "Error rate went up",
  alert: "On-call got an alert",
  incident_created: "Someone opened this incident",
  copilot_analysis: "Copilot matched it to a deployment",
  simulation: "Demo: a service was marked failing",
};

const STATUS_LABEL: Record<string, string> = {
  INVESTIGATING: "Still looking into it",
  OPEN: "Not resolved yet",
  RESOLVED: "Closed",
  MITIGATED: "Partly fixed",
};

function formatTime(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function statusKey(status: string) {
  return status.toLowerCase();
}

function storyFor(detail: {
  title: string;
  service: string | null;
  release_id: number | null;
  timeline: { type: string; message: string }[];
}) {
  const types = new Set((detail.timeline || []).map((e) => e.type));
  const svc = detail.service || "a service";
  if (types.has("simulation")) {
    return `This row is a demo ticket for ${svc}. ReleaseGraph stored a pretend outage. It does not stop a live process by itself.`;
  }
  if (types.has("deployment_completed") && types.has("metric_spike")) {
    return `After a deploy, ${svc} started throwing more errors. On-call was paged and opened this ticket so the team can decide whether to roll back. That is all this page does: show the stored story, then send you to Copilot or the Graph.`;
  }
  return `This is a production problem record for ${svc}. The timeline below is the ordered list of facts we stored — not a live tail of logs.`;
}

export default function IncidentsPage({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.incidents>>>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof api.incident>> | null>(null);
  const [simMsg, setSimMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [loaded, setLoaded] = useState(false);

  function openIncident(id: number) {
    setSelectedId(id);
    setLoadErr("");
    setAnalysis(null);
    api.incident(id).then(setDetail).catch((e) => setLoadErr(e.message));
  }

  async function runAnalysis() {
    if (!selectedId) return;
    setBusy(true);
    try {
      const res = await api.analyzeErrors(projectId, { incident_id: selectedId });
      setAnalysis(res);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    setLoaded(false);
    api
      .incidents(projectId)
      .then((list) => {
        setRows(list);
        const preferred =
          list.find((i) => i.status === "INVESTIGATING") || list[0];
        if (preferred) openIncident(preferred.id);
        else {
          setSelectedId(null);
          setDetail(null);
        }
      })
      .catch((e) => setLoadErr(e.message))
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function triggerFailure() {
    setBusy(true);
    setSimMsg("");
    try {
      const res = await api.simulatePaymentFailure(projectId);
      setSimMsg(`${res.message} The new ticket is selected below.`);
      const list = await api.incidents(projectId);
      setRows(list);
      if (res.incident_id) openIncident(res.incident_id);
      else if (list[0]) openIncident(list[0].id);
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Incidents</h2>
          <p className="muted">
            On-call board for production problems. Open a ticket to see the stored story — this is
            not a live log from the shop.
          </p>
        </div>
      </div>

      {loadErr && <p className="error">{loadErr}</p>}

      {!loaded ? (
        <div className="card">
          <div className="skeleton" style={{ height: 160 }} />
        </div>
      ) : rows.length === 0 ? (
        <div className="card">
          <div className="empty">
            No incidents in the database yet. Seed with{" "}
            <code>python -m releasegraph.seed --reset</code>, or create a demo ticket below.
          </div>
        </div>
      ) : (
        <>
          <div className="chip-row" style={{ marginBottom: "0.85rem" }}>
            {rows.map((i) => (
              <button
                key={i.id}
                type="button"
                className={`chip ${selectedId === i.id ? "active" : ""}`}
                onClick={() => openIncident(i.id)}
              >
                {i.title}
              </button>
            ))}
          </div>

          <div className="card">
            {!detail ? (
              <p className="muted">Select a ticket above.</p>
            ) : (
              <>
                <p className="muted" style={{ marginTop: 0 }}>
                  Status{" "}
                  <span className={`badge ${statusKey(detail.status)}`}>
                    {STATUS_LABEL[detail.status] || detail.status}
                  </span>
                  {" · "}Broken service <span className="pill">{detail.service || "unknown"}</span>
                  {detail.release_id ? (
                    <>
                      {" · "}Tied to{" "}
                      <Link to={`/releases/${detail.release_id}`}>release #{detail.release_id}</Link>
                    </>
                  ) : (
                    " · No related release stored"
                  )}
                </p>
                <h3 style={{ marginTop: "0.85rem", color: "var(--text)", fontSize: "1.15rem" }}>
                  {detail.title}
                </h3>
                <div className="story">{storyFor(detail)}</div>

                <h3 style={{ marginTop: "1.1rem" }}>Timeline (oldest first)</h3>
                {(detail.timeline || []).length === 0 ? (
                  <p className="muted">No events stored for this ticket.</p>
                ) : (
                  <ul className="timeline" style={{ marginTop: 12 }}>
                    {(detail.timeline || []).map((e, idx) => (
                      <li key={idx}>
                        <div className="muted">{formatTime(e.time)}</div>
                        <strong>{EVENT_TITLE[e.type] || e.type.replaceAll("_", " ")}</strong>
                        <div>{e.message}</div>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="guide" style={{ marginTop: "1rem", marginBottom: 0 }}>
                  <h3>What you can do next</h3>
                  <ul>
                    <li>
                      <Link
                        to={`/copilot?q=${encodeURIComponent(`Investigate incident #${detail.id}`)}&ask=1`}
                      >
                        Ask Copilot about this ticket
                      </Link>{" "}
                      — it reads this timeline from the database; it does not invent a cause.
                    </li>
                    <li>
                      <Link to="/graph">Open the Release Graph</Link>
                      {detail.service ? ` — click ${detail.service} to see dependents.` : " — see who depends on whom."}
                    </li>
                    <li>
                      <button type="button" className="secondary" onClick={runAnalysis} disabled={busy}>
                        {busy ? "Analyzing…" : "Analyze files, impact, and fixes"}
                      </button>
                    </li>
                  </ul>
                </div>
                {analysis && (
                  <div style={{ marginTop: "1rem" }}>
                    <AnalysisList
                      issues={analysis.issues}
                      safety={analysis.safety}
                      proposalsCreated={analysis.proposals_created}
                    />
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}

      <div className="card">
        <h3>Optional: create a demo incident</h3>
        <p className="muted">
          Records a failure against a high-criticality service in this project. It does not stop a
          live process.
        </p>
        <button className="danger" onClick={triggerFailure} disabled={busy} style={{ marginTop: 10 }}>
          {busy ? "Creating…" : "Create demo failure incident"}
        </button>
        {simMsg && <p className="ok">{simMsg}</p>}
      </div>
    </>
  );
}
