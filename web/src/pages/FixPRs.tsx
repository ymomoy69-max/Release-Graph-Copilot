import { useEffect, useState } from "react";
import { api, type FixPr } from "../api";
import { notifyGraphRefresh } from "../graphRefresh";

const OPEN = new Set(["OPEN", "NEEDS_HUMAN", "APPROVED"]);

export default function FixPRsPage({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<FixPr[] | null>(null);
  const [users, setUsers] = useState<{ id: number; email: string; full_name: string; role: string }[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<{ id: number; kind: "approve" | "reject" | "merge" } | null>(null);

  function load() {
    setError("");
    Promise.all([api.fixPrs(projectId), api.users()])
      .then(([prs, staff]) => {
        setRows(prs);
        setUsers(staff);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load fix PRs"));
  }

  useEffect(() => {
    setRows(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function act(id: number, kind: "approve" | "reject" | "merge") {
    if (!confirm || confirm.id !== id || confirm.kind !== kind) {
      setConfirm({ id, kind });
      return;
    }
    setBusy(id);
    setError("");
    setNote("");
    try {
      if (kind === "approve") {
        await api.approveFixPr(id);
        setNote("Approved. A second person can close it after the scanner no longer finds this line.");
      }
      if (kind === "reject") {
        await api.rejectFixPr(id);
        setNote("Rejected. Ticket moved to closed.");
      }
      if (kind === "merge") {
        const closed = await api.mergeFixPr(id);
        setNote(closed.verify || "Engine is clean. Ticket left the open board.");
      }
      setConfirm(null);
      load();
      notifyGraphRefresh({ projectId, reason: kind });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function rescanVerify(id: number) {
    setBusy(id);
    setError("");
    setNote("");
    try {
      const res = await api.rescanVerifyFixPr(id);
      setNote(
        res.verify || res.verify_message || `Re-scanned workspace (${res.scan?.issues ?? "?"} issues on disk).`,
      );
      load();
      notifyGraphRefresh({ projectId, reason: "fix_pr_rescan" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Re-scan failed");
    } finally {
      setBusy(null);
    }
  }

  async function assign(id: number, assignee: number) {
    setBusy(id);
    setError("");
    try {
      await api.assignFixPr(id, assignee);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Assign failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Fix PRs</h2>
          <p className="muted">
            Human review board for scanner findings. This is not GitHub. Approve means a person agrees
            the finding is real. Close re-runs the engine: the ticket leaves this list only if that
            line is actually gone. The app does not write to git.
          </p>
        </div>
      </div>

      <div className="guide">
        <h3>How this is different from “AI scanned everything”</h3>
        <ul>
          <li>
            The <strong>workspace scanner and rgc checkers</strong> produce the file, line, and evidence.
            Groq may only rephrase that finding.
          </li>
          <li>
            <strong>Approve</strong> is a human “this is a real bug.” It does not change code.
          </li>
          <li>
            <strong>Re-scan and close</strong> runs the workspace scanner again. If the finding is
            still in the file, the ticket stays. If it is gone, the ticket drops off the open board.
          </li>
          <li>
            Click an action twice to confirm. The LLM cannot approve or close. A second person (or
            admin) must close after approve.
          </li>
        </ul>
      </div>

      {error && <p className="error">{error}</p>}
      {note && <p className="ok">{note}</p>}

      {!rows ? (
        <div className="card">
          <div className="skeleton" style={{ height: 140 }} />
        </div>
      ) : rows.length === 0 ? (
        <div className="empty">
          No fix PRs yet. Scan a workspace on Readiness — open issues become assigned tickets here.
        </div>
      ) : (
        <>
        {rows.some((pr) => !OPEN.has(pr.status)) && (
          <label className="muted" style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={showClosed}
              onChange={(e) => setShowClosed(e.target.checked)}
            />
            Show closed tickets ({rows.filter((pr) => !OPEN.has(pr.status)).length})
          </label>
        )}
        {rows.filter((pr) => showClosed || OPEN.has(pr.status)).length === 0 ? (
          <div className="empty">
            {showClosed
              ? "No tickets in this project."
              : "Open board is empty. Closed tickets are hidden — tick “Show closed” if you need history, or scan on Readiness to open new ones."}
          </div>
        ) : (
        rows.filter((pr) => showClosed || OPEN.has(pr.status)).map((pr) => (
          <article key={pr.id} className={`card issue-card ${pr.severity}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <strong>
                #{pr.number} {pr.title}
              </strong>
              <span className={`badge ${pr.status.toLowerCase()}`}>{pr.status.replace("_", " ")}</span>
            </div>
            <p className="muted" style={{ margin: "0.4rem 0 0" }}>
              {pr.file}
              {pr.line ? `:${pr.line}` : ""}
              {pr.service ? ` · ${pr.service}` : ""}
              {pr.confidence ? ` · confidence ${pr.confidence}` : ""}
            </p>
            <div className="chip-row" style={{ marginTop: 8 }}>
              <span className="badge go">Engine finding</span>
              {pr.llm_accepted ? (
                <span className="badge medium">Groq wording only</span>
              ) : (
                <span className="badge neutral">No LLM rewrite</span>
              )}
              {pr.human_required && <span className="badge warning">Needs human</span>}
              <span className="badge neutral">In-app review</span>
            </div>
            <p style={{ margin: "0.7rem 0 0" }}>
              <strong>Assigned to</strong>{" "}
              <select
                value={pr.assignee?.id || ""}
                disabled={busy === pr.id || pr.status === "MERGED" || pr.status === "REJECTED"}
                onChange={(e) => assign(pr.id, Number(e.target.value))}
                aria-label={`Assignee for PR ${pr.number}`}
              >
                <option value="">Unassigned</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name} ({u.role})
                  </option>
                ))}
              </select>
            </p>
            {pr.affects?.length > 0 && (
              <p className="muted" style={{ margin: "0.45rem 0 0" }}>
                <strong>Affects.</strong> {pr.affects.join(", ")}
              </p>
            )}
            <p style={{ margin: "0.45rem 0 0" }}>
              <strong>Engine fix.</strong> {pr.engine_fix}
            </p>
            {pr.llm_suggestion && (
              <p className="muted" style={{ margin: "0.45rem 0 0" }}>
                <strong>Groq suggestion (unverified as a new finding).</strong> {pr.llm_suggestion}
              </p>
            )}
            {pr.evidence && <pre className="snippet" style={{ marginTop: 10 }}>{pr.evidence}</pre>}
            {(pr.verify_message || pr.verify) && (
              <p className="muted" style={{ margin: "0.5rem 0 0" }}>
                <strong>Last verify.</strong> {pr.verify_message || pr.verify}
              </p>
            )}
            <div className="chip-row" style={{ marginTop: 12 }}>
              {pr.status !== "MERGED" && pr.status !== "REJECTED" && (
                <button
                  type="button"
                  className="ghost"
                  disabled={busy === pr.id}
                  onClick={() => rescanVerify(pr.id)}
                >
                  Re-scan workspace
                </button>
              )}
              {pr.status !== "MERGED" && pr.status !== "REJECTED" && pr.status !== "APPROVED" && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy === pr.id}
                  onClick={() => act(pr.id, "approve")}
                >
                  {confirm?.id === pr.id && confirm.kind === "approve"
                    ? "Click again to confirm approve"
                    : "Approve (human)"}
                </button>
              )}
              {pr.status === "APPROVED" && (
                <button type="button" disabled={busy === pr.id} onClick={() => act(pr.id, "merge")}>
                  {confirm?.id === pr.id && confirm.kind === "merge"
                    ? "Click again — engine re-scans; ticket leaves only if the finding is gone"
                    : "Re-scan and close"}
                </button>
              )}
              {pr.status !== "MERGED" && pr.status !== "REJECTED" && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy === pr.id}
                  onClick={() => act(pr.id, "reject")}
                >
                  {confirm?.id === pr.id && confirm.kind === "reject"
                    ? "Click again to confirm reject"
                    : "Reject"}
                </button>
              )}
            </div>
          </article>
        ))
        )}
        </>
      )}
    </>
  );
}
