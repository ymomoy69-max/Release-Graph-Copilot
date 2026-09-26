import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Login() {
  const [email, setEmail] = useState("admin@acme.demo");
  const [password, setPassword] = useState("admin123!");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();
  const { setAuthToken, token } = useAuth();

  if (token) {
    return <Navigate to="/" replace />;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { access_token } = await api.login(email, password);
      setAuthToken(access_token);
      nav("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Login failed. Ensure the API is running on port 8000.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-wrap">
        <div className="brand" style={{ padding: 0, marginBottom: "1.2rem" }}>
          <div className="brand-mark">RG</div>
          <div>
            <h1>ReleaseGraph Copilot</h1>
            <p className="muted">Release intelligence for engineering teams</p>
          </div>
        </div>
        <h2>Sign in</h2>
        <p className="muted">
          Demo account is prefilled. Employees: priya / sam / jordan @acme.demo (engineer123!) to
          verify Fix PRs. After sign-in, scan a workspace on <strong>Readiness</strong>.
        </p>
        <form onSubmit={submit}>
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required autoComplete="username" />
          <label>Password</label>
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            required
            autoComplete="current-password"
          />
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading} style={{ marginTop: "1.25rem", width: "100%" }}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
