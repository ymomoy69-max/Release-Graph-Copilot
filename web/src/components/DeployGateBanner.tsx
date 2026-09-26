import { Link } from "react-router-dom";
import type { DeployGate } from "../api";

export default function DeployGateBanner({ gate }: { gate: DeployGate | null | undefined }) {
  if (!gate || (!gate.blocked && gate.issue_count === 0)) return null;
  return (
    <div className={`card ${gate.blocked ? "deploy-blocked" : ""}`} style={{ marginBottom: "1rem" }}>
      <h3 style={{ marginTop: 0 }}>{gate.blocked ? "Deploy blocked" : "Scanner findings on disk"}</h3>
      {gate.message && <p className="error" style={{ marginTop: 0 }}>{gate.message}</p>}
      {gate.findings.length > 0 && (
        <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
          {gate.findings.map((f) => (
            <li key={`${f.code}-${f.file}`}>
              <code>{f.code}</code> in <code>{f.file}</code>
              {f.service ? ` (${f.service})` : ""}
              {f.incident_id ? (
                <>
                  {" · "}
                  <Link to={`/incidents?pick=${f.incident_id}`}>incident #{f.incident_id}</Link>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {!gate.blocked && gate.issue_count > 0 && (
        <p className="muted" style={{ marginBottom: 0 }}>
          Non-blocking findings — fix on <Link to="/fix-prs">Fix PRs</Link> before production if you can.
        </p>
      )}
    </div>
  );
}
