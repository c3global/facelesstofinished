import React, { useState, useEffect, useCallback, createContext, useContext } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import axios from "axios";
import Studio from "./pages/Studio";
import Scripts from "./pages/Scripts";
import Login from "./pages/Login";
import Header from "./components/Header";
import "./App.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "f48_studio_token";
const THEME_KEY = "f48_studio_theme";

axios.defaults.timeout = 30000;

// Script generation endpoints can take 60-120s for long-form Claude calls
export const longApiClient = axios.create({ baseURL: API, timeout: 180000 });
longApiClient.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

const AuthCtx = createContext(null);
const ThemeCtx = createContext(null);

export const useAuth = () => useContext(AuthCtx);
export const useTheme = () => useContext(ThemeCtx);

export const apiClient = axios.create({ baseURL: API });
apiClient.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem(THEME_KEY) || "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return (
    <ThemeCtx.Provider value={{ theme, toggle }}>
      {children}
    </ThemeCtx.Provider>
  );
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const t = localStorage.getItem(TOKEN_KEY);
    if (!t) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const r = await apiClient.get("/auth/me");
      setUser(r.data);
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (email) => {
    const r = await apiClient.post("/auth/check", { email });
    localStorage.setItem(TOKEN_KEY, r.data.token);
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  }, []);

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-loading" data-testid="page-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function RequireStudio({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="page-loading" data-testid="page-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.entitlements?.includes("studio"))
    return <div className="page-locked" data-testid="page-locked">Studio access required.</div>;
  return children;
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Header />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/studio" element={<RequireStudio><Studio /></RequireStudio>} />
            <Route path="/scripts" element={<RequireAuth><Scripts /></RequireAuth>} />
            <Route path="/" element={<Navigate to="/scripts" replace />} />
            <Route path="*" element={<Navigate to="/scripts" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
