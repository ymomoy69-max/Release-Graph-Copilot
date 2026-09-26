import { useEffect, useState } from "react";
import { api, type FixPr } from "../api";

export default function FixPRsPage({ projectId }: { projectId: number }) {
  const [rows, setRows] = useState<FixPr[] | null>(null);
  const [users, setUsers] = useState<{ id: number; email: string; full_name: string; role: string }[]>([]);
  const [error, setError] = useState("");
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
    try {
      if (kind === "approve") await api.approveFixPr(id);
      if (kind === "reject") await api.rejectFixPr(id);
      if (kind === "merge") await api.mergeFixPr(id);
      setConfirm(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
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
            In-app demo tickets assigned to employees. This is not GitHub and not Jira — it shows how a
            human verifies engine findings before anything is marked merged. The app does not write to git.
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
            Each PR is assigned to an engineer. A person must <strong>approve</strong>, then a release
            manager or admin marks <strong>merged</strong> (demo status only).
          </li>
          <li>
            Click an action twice to confirm. The LLM cannot approve or merge.
          </li>
        </ul>
      </div>

      {error && <p className="error">{error}</p>}

      {!rows ? (
        <div className="card">
          <div className="skeleton" style={{ height: 140 }} />
        </div>
      ) : rows.length === 0 ? (
        <div className="empty">
          No fix PRs yet. Scan a workspace on Readiness — open issues become assigned tickets here.
        </div>
      ) : (
        rows.map((pr) => (
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
              <span className="badge neutral">Demo · not GitHub</span>
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
            <div className="chip-row" style={{ marginTop: 12 }}>
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
                    ? "Click again to mark merged (demo)"
                    : "Mark merged (demo)"}
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
  );
}
