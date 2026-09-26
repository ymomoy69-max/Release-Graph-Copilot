import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type AnalysisPayload, type ShopStatus } from "../api";
import { notifyGraphRefresh } from "../graphRefresh";
import AnalysisList from "./AnalysisList";

const EVENT_TITLE: Record<string, string> = {
  deployment_completed: "A release went to production",
  metric_spike: "Error rate went up",
  alert: "On-call got an alert",
  incident_created: "Someone opened this incident",
  copilot_analysis: "Copilot matched it to a deployment",
  scan_finding: "Workspace scanner found this",
  scan_cleared: "Scanner no longer sees this issue",
  failure_mode_enabled: "Payment failure mode turned on",
  checkout_failed: "Checkout failed",
  payments_restored: "Payments restored in the shop",
};

const STATUS_LABEL: Record<string, string> = {
  INVESTIGATING: "Still looking into it",
  OPEN: "Not resolved yet",
  RESOLVED: "Closed",
  MITIGATED: "Partly fixed",
};

const OPEN_INCIDENT = new Set(["OPEN", "INVESTIGATING", "MITIGATED"]);

function firstOpen<T extends { id: number; status: string }>(list: T[]): T | undefined {
  return list.find((i) => OPEN_INCIDENT.has(i.status));
}

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
  if (types.has("checkout_failed")) {
    if (types.has("payments_restored")) {
      return `Checkout failed while payment failure mode was on. Payments were restored in the shop, so this ticket closed automatically.`;
    }
    return `A live checkout failed because ${svc} rejected the payment. Restore payments on the shop (${"http://127.0.0.1:8082"}) — when failure mode turns off, this ticket closes on the next refresh.`;
  }
  if (types.has("scan_finding") || detail.title.startsWith("Code scan:")) {
    return `This ticket was opened from a workspace scan of ${svc}. If you fix the file on disk and rescan, the ticket can auto-resolve when the finding disappears.`;
  }
  if (types.has("deployment_completed") && types.has("metric_spike")) {
    return `After a deploy, ${svc} started throwing more errors. On-call was paged and opened this ticket so the team can decide whether to roll back. That is all this page does: show the stored story, then send you to Copilot or the Graph.`;
  }
  return `This is a production problem record for ${svc}. The timeline below is the ordered list of facts we stored — not a live tail of logs.`;
}

export default function IncidentsPage({ projectId }: { projectId: number }) {
  const [searchParams] = useSearchParams();
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.incidents>>>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof api.incident>> | null>(null);
  const [simMsg, setSimMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadErr, setLoadErr] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [shop, setShop] = useState<ShopStatus | null>(null);
  const [shopSyncMsg, setShopSyncMsg] = useState("");

  const openCount = rows.filter((i) => OPEN_INCIDENT.has(i.status)).length;
  const closedCount = rows.length - openCount;
  const chipRows = showClosed ? rows : rows.filter((i) => OPEN_INCIDENT.has(i.status));

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
      notifyGraphRefresh({ projectId, reason: "incident_analysis" });
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  function applyIncidentList(list: Awaited<ReturnType<typeof api.incidents>>, pickPreferred: boolean) {
    setRows(list);
    const stillThere = selectedId != null && list.some((i) => i.id === selectedId);
    if (pickPreferred) {
      const preferred = firstOpen(list) || list.find((i) => i.status === "INVESTIGATING") || list[0];
      if (preferred) openIncident(preferred.id);
      else {
        setSelectedId(null);
        setDetail(null);
      }
    } else if (stillThere && selectedId != null) {
      api.incident(selectedId).then(setDetail).catch(() => {});
    } else if (!firstOpen(list)) {
      setSelectedId(null);
      setDetail(null);
    }
  }

  useEffect(() => {
    api.shopStatus().then(setShop).catch(() => setShop(null));
  }, []);

  useEffect(() => {
    const pick = searchParams.get("pick");
    if (pick && loaded) {
      const id = Number(pick);
      if (Number.isFinite(id)) openIncident(id);
    }
  }, [searchParams, loaded]);

  async function syncShopTickets() {
    setBusy(true);
    setShopSyncMsg("");
    try {
      const res = await api.syncShopIncidents(projectId);
      setShop(res);
      const list = await api.incidents(projectId);
      applyIncidentList(list, false);
      setShopSyncMsg(
        res.payment_status === "ok"
          ? "Payments look healthy — checkout incidents synced."
          : "Synced with shop (payment failure mode may still be on).",
      );
      notifyGraphRefresh({ projectId, reason: "shop_sync" });
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Shop sync failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    setLoaded(false);
    api
      .incidents(projectId)
      .then((list) => applyIncidentList(list, true))
      .catch((e) => setLoadErr(e.message))
      .finally(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      api
        .incidents(projectId)
        .then((list) => applyIncidentList(list, false))
        .catch(() => {});
    }, 15_000);
    const onFocus = () => {
      api
        .incidents(projectId)
        .then((list) => applyIncidentList(list, false))
        .catch(() => {});
    };
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, selectedId]);

  async function rescanIncidents() {
    setBusy(true);
    setSimMsg("");
    setLoadErr("");
    try {
      const path = (await api.projects()).find((p) => p.id === projectId)?.workspace_path;
      if (!path?.trim()) {
        setLoadErr("Set a workspace path on Readiness and scan first.");
        return;
      }
      await api.scanWorkspace(path, projectId);
      const list = await api.incidents(projectId);
      applyIncidentList(list, true);
      setSimMsg("Rescanned the workspace and synced incidents from findings on disk.");
      notifyGraphRefresh({ projectId, reason: "incident_rescan" });
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Rescan failed");
    } finally {
      setBusy(false);
    }
  }

  async function triggerFailure() {
    setBusy(true);
    setSimMsg("");
    try {
      const res = await api.runCheckoutFailure(projectId);
      setSimMsg(`${res.message} The ticket is selected below.`);
      const list = await api.incidents(projectId);
      applyIncidentList(list, false);
      if (res.incident_id) openIncident(res.incident_id);
      else if (list[0]) openIncident(list[0].id);
      notifyGraphRefresh({ projectId, reason: "checkout_failure" });
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Checkout failed to run");
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
            No incidents yet. Scan a workspace on Readiness (opens tickets from code findings), or run a
            live failing checkout below.
          </div>
        </div>
      ) : (
        <>
          <div className="page-head" style={{ marginBottom: "0.5rem", alignItems: "center" }}>
            <p className="muted" style={{ margin: 0 }}>
              {openCount} open
              {closedCount > 0 ? ` · ${closedCount} closed (code-scan tickets auto-close after rescan)` : ""}
            </p>
            {closedCount > 0 && (
              <button
                type="button"
                className="secondary"
                onClick={() => setShowClosed((v) => !v)}
              >
                {showClosed ? "Hide closed" : `Show closed (${closedCount})`}
              </button>
            )}
          </div>
          <div className="chip-row" style={{ marginBottom: "0.85rem" }}>
            {chipRows.map((i) => (
              <button
                key={i.id}
                type="button"
                className={`chip ${selectedId === i.id ? "active" : ""}`}
                onClick={() => openIncident(i.id)}
              >
                {i.title}
                {!OPEN_INCIDENT.has(i.status) ? " (closed)" : ""}
              </button>
            ))}
          </div>
          {chipRows.length === 0 && closedCount > 0 && (
            <p className="muted" style={{ marginBottom: "0.85rem" }}>
              No open tickets. Use &ldquo;Show closed&rdquo; to see resolved code-scan incidents.
            </p>
          )}

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
        <h3>Rescan workspace → sync incidents</h3>
        <p className="muted">
          Re-runs the scanner on the project workspace path and opens or closes <strong>Code scan:</strong>{" "}
          tickets to match code on disk (same as Readiness → Scan workspace). Checkout failures close
          automatically when you restore payments on the shop (this page polls every ~15s).
        </p>
        <button type="button" className="secondary" onClick={rescanIncidents} disabled={busy} style={{ marginTop: 10 }}>
          {busy ? "Scanning…" : "Rescan & sync incidents"}
        </button>
      </div>

      <div className="card">
        <h3>Live shop (checkout incidents)</h3>
        <p className="muted">
          Checkout tickets close when payment failure mode is off in the running shop.
          {shop
            ? ` Gateway: ${shop.gateway_url} · payments: ${shop.payment_status}.`
            : " Start the shop with scripts/dev-all.sh or python demo/ecommerce/run_all.py."}
        </p>
        <div className="row" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
          {shop?.storefront_url && (
            <a className="secondary" href={shop.storefront_url} target="_blank" rel="noreferrer" style={{ display: "inline-block", padding: "0.55rem 1rem", textDecoration: "none" }}>
              Open shop & restore payments
            </a>
          )}
          <button type="button" className="secondary" onClick={syncShopTickets} disabled={busy}>
            {busy ? "Syncing…" : "Check shop & sync tickets"}
          </button>
        </div>
        {shopSyncMsg && <p className="ok">{shopSyncMsg}</p>}
      </div>

      <div className="card">
        <h3>Run a failing checkout</h3>
        <p className="muted">
          Turns payment failure on in the running shop, places one order for sku-100, and saves this
          ticket from the gateway response. Start the shop first with{" "}
          <code>python demo/ecommerce/run_all.py</code>. Payments stay failed until you restore them
          on the shop page. Another click places another order and adds it to the same open ticket.
        </p>
        <button className="danger" onClick={triggerFailure} disabled={busy} style={{ marginTop: 10 }}>
          {busy ? "Placing order…" : "Run a failing checkout"}
        </button>
        {simMsg && <p className="ok">{simMsg}</p>}
      </div>
    </>
  );
}
