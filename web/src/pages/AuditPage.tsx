import { useEffect, useState } from "react";
import { api } from "../api";

const ACTION_LABEL: Record<string, string> = {
  "copilot.ask": "Asked Copilot a question",
  "incident.create": "Created an incident",
  "simulation.service_failure": "Demo: created a service-failure incident",
  "simulation.payment_failure": "Demo: created a payment-failure incident",
  "workspace.scan": "Scanned a workspace",
  "analysis.errors": "Ran error analysis",
  "fix_pr.assign": "Assigned a demo fix PR",
  "fix_pr.approve": "Approved a demo fix PR",
  "fix_pr.reject": "Rejected a demo fix PR",
  "fix_pr.merge": "Marked a demo fix PR merged",
  "release.rollback": "Rolled back a release",
  "readiness.check": "Ran a readiness (GO / NO-GO) check",
  "simulator.deploy": "Demo: simulated a deploy",
};

export default function AuditPage() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof api.audit>> | null>(null);

  useEffect(() => {
    api.audit().then(setRows);
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Audit log</h2>
          <p className="muted">
            A receipt of important actions: Copilot, readiness, rollbacks, and human approve/merge of
            demo fix PRs. Nothing here changes the live shop or writes to GitHub.
          </p>
        </div>
      </div>
      <div className="guide">
        <h3>How to read it</h3>
        <ul>
          <li>
            <strong>Human</strong> means a person clicked (sign-in user). <strong>AI</strong> means
            Copilot recorded the ask.
          </li>
          <li>Use this page if you need to prove who approved a rollback.</li>
        </ul>
      </div>
      <div className="card">
        {!rows ? (
          <div className="skeleton" style={{ height: 140 }} />
        ) : rows.length === 0 ? (
          <div className="empty">No audit events yet. Ask Copilot or run a readiness check.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>What happened</th>
                  <th>On</th>
                  <th>Who</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td className="muted">{new Date(e.timestamp).toLocaleString()}</td>
                    <td>{ACTION_LABEL[e.action] || e.action}</td>
                    <td>
                      {e.entity_type} #{e.entity_id}
                    </td>
                    <td>{e.user_email || "—"}</td>
                    <td>
                      <span className={`badge ${e.ai_generated ? "neutral" : "low"}`}>
                        {e.ai_generated ? "AI" : "Human"}
                      </span>
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
