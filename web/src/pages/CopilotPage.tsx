import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";

const PLAYBOOKS = [
  {
    q: "Is it safe to deploy to production right now?",
    why: "Uses release train, deploy gate, workspace scan, and open incidents.",
  },
  {
    q: "What breaks if payment-service fails?",
    why: "Blast radius on the live dependency graph plus open incidents.",
  },
  {
    q: "What scanner issues block deploy?",
    why: "Reads blocking findings and linked incidents from the workspace.",
  },
];

const SUGGESTIONS = [
  ...PLAYBOOKS,
  { q: "What is wrong, which file, and what is the fix?", why: "Engine findings first; Groq may rephrase." },
  { q: "Which fix PRs are assigned to employees?", why: "Lists in-app review tickets from the scanner." },
  { q: "What changed in the latest release?", why: "Lists stored commits and services for the newest release." },
  { q: "Investigate this incident", why: "Reads the incident timeline plus blast radius." },
];

export default function CopilotPage({ projectId }: { projectId: number }) {
  const [params] = useSearchParams();
  const [question, setQuestion] = useState(() => params.get("q") || SUGGESTIONS[0].q);
  const [answer, setAnswer] = useState("");
  const [tools, setTools] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(false);
  const [showTools, setShowTools] = useState(true);
  const lastAuto = useRef("");

  async function runAsk(q: string) {
    setLoading(true);
    try {
      const res = await api.copilotAsk(projectId, q);
      setAnswer(res.answer);
      setTools(res.tool_calls);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const q = params.get("q");
    const shouldAsk = params.get("ask") === "1";
    if (q) setQuestion(q);
    if (shouldAsk && q) {
      const key = `${projectId}:${q}`;
      if (lastAuto.current !== key) {
        lastAuto.current = key;
        void runAsk(q);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, projectId]);

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Copilot</h2>
          <p className="muted">
            Looks up this project with tools. Groq may rephrase tool results. It will not invent
            files, and it cannot approve Fix PRs — a person does that.
          </p>
        </div>
      </div>
      <div className="guide">
        <h3>Ask about the current workspace</h3>
        <ol>
          <li>Scan a workspace on <Link to="/readiness">Readiness</Link>.</li>
          <li>Ask what is wrong — file, blast radius, and engine fix. Groq only rephrases.</li>
          <li>Open <Link to="/fix-prs">Fix PRs</Link> to assign and approve scanner tickets.</li>
          <li>Open <Link to="/incidents">Incidents</Link> and use “Ask Copilot about this ticket”.</li>
        </ol>
      </div>
      <div className="card">
        <h3>Playbooks (tool-backed)</h3>
        <div className="chip-row" style={{ marginTop: 8, marginBottom: 12 }}>
          {PLAYBOOKS.map((s) => (
            <button
              key={s.q}
              type="button"
              className={`chip ${question === s.q ? "active" : ""}`}
              onClick={() => setQuestion(s.q)}
              title={s.why}
            >
              {s.q}
            </button>
          ))}
        </div>
        <h3>More questions</h3>
        <div className="chip-row" style={{ marginTop: 10 }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s.q}
              type="button"
              className={`chip ${question === s.q ? "active" : ""}`}
              onClick={() => setQuestion(s.q)}
              title={s.why}
            >
              {s.q}
            </button>
          ))}
        </div>
        <p className="muted">{SUGGESTIONS.find((s) => s.q === question)?.why}</p>
        <label>Or type your own</label>
        <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button onClick={() => runAsk(question)} disabled={loading} style={{ marginTop: 12 }}>
          {loading ? "Looking up evidence…" : "Ask"}
        </button>
      </div>
      {answer && (
        <div className="card">
          <h3>Answer</h3>
          <pre className="snippet">{answer}</pre>
        </div>
      )}
      {tools.length > 0 && (
        <div className="card">
          <div className="page-head" style={{ marginBottom: 8 }}>
            <h3>Proof — tools that ran</h3>
            <button type="button" className="ghost" onClick={() => setShowTools(!showTools)}>
              {showTools ? "Hide" : "Show"}
            </button>
          </div>
          {showTools && <pre className="snippet">{JSON.stringify(tools, null, 2)}</pre>}
        </div>
      )}
    </>
  );
}
