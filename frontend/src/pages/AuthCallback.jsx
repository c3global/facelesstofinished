import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth, apiClient } from "../App";

// Magic-link callback landing page.
//
// After the backend verifies the magic-link token it 302-redirects to
// `<origin>/auth/callback#jwt=<JWT>&email=<email>`. We keep the JWT in the
// URL fragment (not query) so it never hits the backend access log and
// isn't cached by intermediary proxies.
//
// This page:
//   1. Parses the fragment.
//   2. Stashes the JWT under the same key AuthProvider reads on refresh.
//   3. Calls `/api/auth/me` to confirm the token is valid and populates
//      the auth context with the user object (so RequireAuth doesn't
//      bounce them back to /login).
//   4. Redirects to /scripts on success, /login?err=... on failure.
const TOKEN_KEY = "f48_studio_token";

export default function AuthCallback() {
  const nav = useNavigate();
  const { refresh } = useAuth();
  const [msg, setMsg] = useState("Finishing sign-in…");

  useEffect(() => {
    const run = async () => {
      const hash = (window.location.hash || "").replace(/^#/, "");
      const params = new URLSearchParams(hash);
      const jwt = params.get("jwt");
      const err = params.get("err") || new URLSearchParams(window.location.search).get("err");
      if (err) {
        setMsg("Sign-in link expired or invalid.");
        const dest = `/login?err=${encodeURIComponent(err)}`;
        setTimeout(() => nav(dest, { replace: true }), 900);
        return;
      }
      if (!jwt) {
        setMsg("No sign-in token found in the link.");
        setTimeout(() => nav("/login?err=missing_token", { replace: true }), 900);
        return;
      }
      try {
        localStorage.setItem(TOKEN_KEY, jwt);
        localStorage.setItem("f48_studio_returning", "1");
      } catch { /* storage blocked — the sign-in still works this tab */ }
      try {
        // Verify + hydrate the auth context. The interceptor picks the
        // token up from localStorage so we don't need to pass it here.
        await apiClient.get("/auth/me");
        if (typeof refresh === "function") await refresh();
        setMsg("Signed in — redirecting…");
        // Clean the URL so re-visiting the tab doesn't re-enter this flow.
        try {
          window.history.replaceState(null, "", "/auth/callback");
        } catch { /* ignore */ }
        nav("/scripts", { replace: true });
      } catch (e) {
        try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
        const detail = e?.response?.data?.detail || "verify_failed";
        setMsg("Could not complete sign-in.");
        setTimeout(() => nav(`/login?err=${encodeURIComponent(detail)}`, { replace: true }), 900);
      }
    };
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="auth-callback-wrap" data-testid="auth-callback">
      <div className="auth-callback-card" data-testid="auth-callback-card">
        <div className="auth-callback-spinner" aria-hidden="true" />
        <p className="auth-callback-msg" data-testid="auth-callback-msg">{msg}</p>
      </div>
    </div>
  );
}
