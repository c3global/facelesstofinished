import React, { useState, useEffect, useCallback, createContext, useContext } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import axios from "axios";
import Studio from "./pages/Studio";
import Scripts from "./pages/Scripts";
import Resources from "./pages/Resources";
import Thumbnails from "./pages/Thumbnails";
import Redeem from "./pages/Redeem";
import Login from "./pages/Login";
import Admin from "./pages/Admin";
import Header from "./components/Header";
import Footer from "./components/Footer";
import "./App.css";

// API base — absolute in dev/preview (REACT_APP_BACKEND_URL set), relative in
// production where the Netlify reverse-proxy at faceless48.c3global.co/studio
// already routes `/api/*` to this backend. Empty/undefined env var falls back
// to "" so axios issues relative paths.
const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;
const TOKEN_KEY = "f48_studio_token";
const THEME_KEY = "f48_studio_theme";

axios.defaults.timeout = 30000;

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
    // Durable "you've signed in before" flag — survives logout + token expiry
    // so the Login page can flip between first-time hero copy and "Welcome
    // back." for returning customers. Wiped only if the user clears site data.
    try { localStorage.setItem("f48_studio_returning", "1"); } catch {}
    setUser(r.data.user);
    // Return the full response so callers can read the optional `welcome`
    // field (set on first sign-in after a Pinball auto-grant). The Login
    // page reads this to fire a one-shot "Welcome — access granted" toast.
    return { user: r.data.user, welcome: r.data.welcome || null };
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
    return <EntitlementPaywall feature="studio" />;
  return children;
}

// Paywall card shown when a logged-in user tries to access a feature they
// haven't purchased. Each feature redirects to its own sprint.c3global.co
// sales page. The component lives here (vs a separate file) because the
// gating logic + UI are tightly coupled and we want to keep App.js as the
// single source of truth for route guards.
export function EntitlementPaywall({ feature }) {
  const meta = {
    studio: {
      title: "Studio access required.",
      desc:
        "Your Faceless to Finished account doesn't include the Studio yet. Upgrade to unlock 1,200+ HeyGen avatars, 2,300+ voices, and the Faceless render pipeline.",
      cta: "Unlock Studio",
      href: "https://sprint.c3global.co/f2f48studio",
    },
    shorts: {
      title: "Shorts access required.",
      desc:
        "Short-form scripts (TikTok, Reels, YouTube Shorts) require the Faceless to Finished bundle. Grab it once and unlock unlimited shorts script generation.",
      cta: "Get Faceless to Finished",
      // Direct checkout link — bypasses the sales page so buyers who
      // already know what they want can complete in one step. Updated
      // 2026-02-23 per Charity's request.
      href: "https://hub.c3global.co/payment-link/6a151b0d3f4eb69bef72feae",
    },
  }[feature] || {
    title: "Access required.",
    desc: "Please upgrade your account to access this feature.",
    cta: "Upgrade",
    href: "https://sprint.c3global.co/faceless",
  };
  return (
    <div className="paywall-wrap" data-testid={`paywall-${feature}`}>
      <div className="paywall-card">
        <p className="paywall-eyebrow">Upgrade Required</p>
        <h1 className="paywall-title">{meta.title}</h1>
        <p className="paywall-desc">{meta.desc}</p>
        <a
          className="paywall-cta"
          href={meta.href}
          target="_blank"
          rel="noopener noreferrer"
          data-testid={`paywall-${feature}-cta`}
        >
          {meta.cta} →
        </a>
        <p className="paywall-note">
          Already purchased? Make sure you&apos;re signed in with the email you used
          at checkout. Email{" "}
          <a className="paywall-link" href="mailto:support@c3global.co">support@c3global.co</a>{" "}
          if you need help.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter basename={process.env.PUBLIC_URL || ""}>
          <Header />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/studio" element={<RequireStudio><Studio /></RequireStudio>} />
            <Route path="/scripts" element={<RequireAuth><Scripts /></RequireAuth>} />
            <Route path="/thumbnails" element={<RequireAuth><Thumbnails /></RequireAuth>} />
            <Route path="/resources" element={<RequireAuth><Resources /></RequireAuth>} />
            <Route path="/redeem" element={<Redeem />} />
            <Route path="/admin" element={<RequireAuth><Admin /></RequireAuth>} />
            <Route path="/" element={<Navigate to="/scripts" replace />} />
            <Route path="*" element={<Navigate to="/scripts" replace />} />
          </Routes>
          <FooterGate />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

// Footer is hidden on /login (the login page already shows the full landing
// hero — a footer below it would just add clutter). On every other route,
// the Footer mounts at the bottom of the viewport. Mirrors the Header's
// `showNav` pattern in components/Header.jsx.
function FooterGate() {
  const loc = useLocation();
  if (loc.pathname === "/login") return null;
  return <Footer />;
}
