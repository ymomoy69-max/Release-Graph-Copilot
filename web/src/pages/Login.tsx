import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

const DEV_HINT = import.meta.env.DEV;

export default function Login() {
  const [email, setEmail] = useState(DEV_HINT ? "admin@acme.demo" : "");
  const [password, setPassword] = useState(DEV_HINT ? "admin123!" : "");
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
          Product data comes from the workspace you scan on <strong>Readiness</strong>. Login accounts
          are only for access control.
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
          <button type="submit" disabled={loading} style={{ marginTop: 14, width: "100%" }}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
