import { Link } from "react-router-dom";
import type { AnalysisIssue, AnalysisPayload } from "../api";

export default function AnalysisList({
  issues,
  safety,
  proposalsCreated,
}: {
  issues: AnalysisIssue[];
  safety?: AnalysisPayload["safety"];
  proposalsCreated?: number;
}) {
  return (
    <>
      {safety && (
        <div className="guide">
          <h3>How this analysis is gated</h3>
          <ul>
            <li>
              <strong>Engine is source of truth.</strong> File, line, and evidence come from the
              scanner and checkers — not from Groq inventing a path.
            </li>
            <li>
              {safety.llm_used
                ? `Groq rephrased ${safety.llm_accepted || 0} finding(s); ${safety.llm_rejected || 0} LLM rewrite(s) were discarded.`
                : "Groq wording was not applied (offline, disabled, or no key). The engine findings still stand."}
            </li>
            <li>
              A person must review each ticket on <Link to="/fix-prs">Fix PRs</Link>
              {typeof proposalsCreated === "number" ? ` (${proposalsCreated} opened this run)` : ""}.
            </li>
          </ul>
        </div>
      )}
      {!issues.length ? (
        <div className="empty">No file-level issues in this scan.</div>
      ) : (
        issues.map((issue, idx) => (
          <div key={`${issue.file}-${issue.line}-${idx}`} className={`card issue-card ${issue.severity}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <strong>
                {issue.file}
                {issue.line ? `:${issue.line}` : ""}
              </strong>
              <span className={`badge ${issue.severity}`}>{issue.severity}</span>
            </div>
            <div className="chip-row" style={{ marginTop: 8 }}>
              <span className="badge go">Engine-verified</span>
              {issue.llm_accepted ? (
                <span className="badge medium">Groq wording</span>
              ) : (
                <span className="badge neutral">LLM not used on this row</span>
              )}
              {issue.human_required && <span className="badge warning">Needs human</span>}
              {issue.confidence && <span className="badge neutral">{issue.confidence} confidence</span>}
            </div>
            {issue.service && (
              <p className="muted" style={{ margin: "0.35rem 0 0" }}>
                Service <span className="pill">{issue.service}</span>
              </p>
            )}
            <p style={{ margin: "0.55rem 0 0" }}><strong>What’s wrong.</strong> {issue.problem}</p>
            {issue.affects?.length > 0 && (
              <p className="muted" style={{ margin: "0.35rem 0 0" }}>
                <strong>Affects.</strong> {issue.affects.join(", ")}
              </p>
            )}
            <p style={{ margin: "0.35rem 0 0" }}><strong>Consequences.</strong> {issue.consequences}</p>
            <p style={{ margin: "0.35rem 0 0" }}>
              <strong>Engine fix.</strong> {issue.engine_fix || issue.fix}
            </p>
            {issue.llm_accepted && issue.llm_fix && issue.llm_fix !== (issue.engine_fix || issue.fix) && (
              <p className="muted" style={{ margin: "0.35rem 0 0" }}>
                <strong>Groq wording.</strong> {issue.llm_fix}
              </p>
            )}
            {issue.evidence && <pre className="snippet" style={{ marginTop: 10 }}>{issue.evidence}</pre>}
          </div>
        ))
      )}
    </>
  );
}
