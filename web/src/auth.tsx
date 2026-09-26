import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { getToken, setToken as persistToken } from "./api";

type AuthContextValue = {
  token: string | null;
  setAuthToken: (token: string | null) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());

  const setAuthToken = useCallback((value: string | null) => {
    persistToken(value);
    setTokenState(value);
  }, []);

  const value = useMemo(() => ({ token, setAuthToken }), [token, setAuthToken]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
