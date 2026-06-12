import React, { useState, useEffect, useCallback, createContext, useContext } from "react";
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import axios from "axios";
import Studio from "./pages/Studio";
import Login from "./pages/Login";
import Header from "./components/Header";
import "./App.css";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const TOKEN_KEY = "f48_studio_token";

axios.defaults.timeout = 30000;

const AuthCtx = createContext(null);

export const useAuth = () => useContext(AuthCtx);

export const apiClient = axios.create({ baseURL: API });
apiClient.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

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
    <AuthProvider>
      <BrowserRouter>
        <Header />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/studio" element={<RequireStudio><Studio /></RequireStudio>} />
          <Route path="/" element={<Navigate to="/studio" replace />} />
          <Route path="*" element={<Navigate to="/studio" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
