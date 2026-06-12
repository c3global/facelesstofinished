import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../App";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await login(email.trim());
      nav("/studio");
    } catch (e) {
      const msg = e?.response?.data?.detail || "Could not sign in. Use the email you bought with.";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap" data-testid="login-page">
      <form className="login-card" onSubmit={submit} data-testid="login-form">
        <p className="login-eyebrow">Studio Access</p>
        <h1 className="login-title">Welcome back.</h1>
        <p className="login-sub">
          Sign in with the email you used to purchase Faceless to Finished. We use it to verify your Studio entitlement —
          no password needed.
        </p>
        <div className="login-form">
          <input
            type="email"
            autoFocus
            placeholder="you@email.com"
            className="login-input"
            data-testid="login-email-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <button
            type="submit"
            className="login-cta"
            data-testid="login-submit-btn"
            disabled={busy || !email}
          >
            {busy ? "Signing in…" : "Enter Studio"}
          </button>
          {err && <p className="login-error" data-testid="login-error">{err}</p>}
        </div>
      </form>
    </div>
  );
}
