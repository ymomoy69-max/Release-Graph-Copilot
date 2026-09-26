import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import Dashboard from "./pages/Dashboard";
import Releases from "./pages/Releases";
import ReleaseDetail from "./pages/ReleaseDetail";
import GraphPage from "./pages/GraphPage";
import CopilotPage from "./pages/CopilotPage";
import IncidentsPage from "./pages/IncidentsPage";
import AuditPage from "./pages/AuditPage";
import ReadinessPage from "./pages/ReadinessPage";
import Login from "./pages/Login";
import { IconAlert, IconChat, IconDash, IconGraph, IconLog, IconPr, IconReleases, IconShield } from "./icons";
import FixPRsPage from "./pages/FixPRs";

type Project = { id: number; slug: string; name: string; description: string; workspace_path?: string };

function Shell({
  project,
  projects,
  onProject,
}: {
  project: Project;
  projects: Project[];
  onProject: (id: number) => void;
}) {
  const loc = useLocation();
  const { setAuthToken } = useAuth();
  const nav = [
    ["", "Home", "Project snapshot", <IconDash key="d" />],
    ["releases", "Releases", "Versions we shipped", <IconReleases key="r" />],
    ["readiness", "Readiness", "Scan workspace · GO/NO-GO", <IconShield key="s" />],
    ["fix-prs", "Fix PRs", "Assigned tickets · human approve", <IconPr key="p" />],
    ["graph", "Release Graph", "Broken links · who feels it", <IconGraph key="g" />],
    ["incidents", "Incidents", "On-call board", <IconAlert key="i" />],
    ["copilot", "Copilot", "Ask with tools + AI", <IconChat key="c" />],
    ["audit", "Audit log", "Who did what", <IconLog key="a" />],
  ] as const;

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">RG</div>
          <div>
            <h1>ReleaseGraph</h1>
            <p className="muted">{project.name}</p>
          </div>
        </div>
        {projects.length > 1 && (
          <select
            className="project-select"
            value={project.id}
            onChange={(e) => onProject(Number(e.target.value))}
            aria-label="Project"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        )}
        <nav>
          {nav.map(([path, label, hint, icon]) => {
            const to = path ? `/${path}` : "/";
            const active =
              loc.pathname === to ||
              (path === "releases" && loc.pathname.startsWith("/releases")) ||
              (Boolean(path) && path !== "releases" && loc.pathname.startsWith(`/${path}`));
            return (
              <Link
                key={path || "home"}
                to={to}
                title={hint}
                className={`nav-link ${active ? "active" : ""}`}
              >
                {icon}
                <span className="nav-copy">
                  {label}
                  <small>{hint}</small>
                </span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <button
            className="secondary"
            style={{ width: "100%" }}
            onClick={() => {
              setAuthToken(null);
              window.location.href = "/login";
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard project={project} />} />
          <Route path="/releases" element={<Releases projectId={project.id} />} />
          <Route path="/releases/:id" element={<ReleaseDetail />} />
          <Route path="/readiness" element={<ReadinessPage project={project} onProject={onProject} />} />
          <Route path="/fix-prs" element={<FixPRsPage projectId={project.id} />} />
          <Route path="/graph" element={<GraphPage projectId={project.id} />} />
          <Route path="/incidents" element={<IncidentsPage projectId={project.id} />} />
          <Route path="/copilot" element={<CopilotPage projectId={project.id} />} />
          <Route path="/audit" element={<AuditPage />} />
        </Routes>
      </main>
    </div>
  );
}

function AuthenticatedApp() {
  const { token, setAuthToken } = useAuth();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState("");

  function selectProject(id: number) {
    setProjectId(id);
    localStorage.setItem("rgc_project_id", String(id));
  }

  useEffect(() => {
    if (!token) {
      setProjects([]);
      setProjectId(null);
      return;
    }
    setLoadError("");
    api.projects()
      .then((ps) => {
        if (!ps.length) {
          setLoadError("No projects yet. Sign in and scan a workspace on Readiness.");
          return;
        }
        setProjects(ps);
        const saved = Number(localStorage.getItem("rgc_project_id") || 0);
        const chosen = ps.find((p) => p.id === saved) || ps[0];
        selectProject(chosen.id);
      })
      .catch((err) => {
        setProjectId(null);
        const msg = err instanceof Error ? err.message : "Failed to load projects";
        setLoadError(
          `${msg}. Is the API running on port 8000? Use http://127.0.0.1:5173 (Vite) or http://127.0.0.1:8000 after npm run build.`,
        );
        setAuthToken(null);
      });
  }, [token, setAuthToken]);

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  if (loadError) {
    return (
      <div className="login-screen">
        <div className="login-wrap">
          <h2>Could not load app</h2>
          <p className="error">{loadError}</p>
          <button type="button" onClick={() => setAuthToken(null)}>Back to sign in</button>
        </div>
      </div>
    );
  }

  const project = projects.find((p) => p.id === projectId);
  if (!project) {
    return (
      <div className="login-screen">
        <p className="muted">Loading project…</p>
      </div>
    );
  }

  return <Shell project={project} projects={projects} onProject={selectProject} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={<AuthenticatedApp />} />
    </Routes>
  );
}
