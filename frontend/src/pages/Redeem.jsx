import React, { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PartyPopper } from "lucide-react";
import { useAuth, apiClient } from "../App";

// AppSumo license activation page. This is the OAuth redirect URL saved in
// the AppSumo Partner Portal — after checkout AppSumo sends buyers here with
// a single-use ?code= query param. We ask for their email (AppSumo never
// shares it), then POST /api/appsumo/redeem to exchange the code for their
// license_key, link it to the email, and grant entitlements. On success we
// sign them straight in with the existing email-only login.
export default function Redeem() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const code = useMemo(() => (params.get("code") || "").trim(), [params]);

  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      await apiClient.post("/appsumo/redeem", { code, email: email.trim() });
      const { welcome } = await login(email.trim());
      if (welcome) {
        try {
          sessionStorage.setItem("f48_pending_welcome", JSON.stringify(welcome));
        } catch {}
      }
      nav("/scripts");
    } catch (e2) {
      const msg =
        e2?.response?.data?.detail ||
        "Activation failed. Please restart from your AppSumo account, or email support@c3global.co.";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap" data-testid="redeem-page">
      <div className="login-stack">
        <div className="login-grid" style={{ justifyContent: "center" }}>
          <form className="login-card" onSubmit={submit} data-testid="redeem-form">
            <p className="login-eyebrow">
              <PartyPopper size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
              AppSumo Activation
            </p>
            <h2 className="login-title" data-testid="redeem-title">
              Welcome, Sumo-ling!
            </h2>
            {code ? (
              <>
                <p className="login-sub">
                  You&apos;re one step away. Enter the email you&apos;d like to use for your
                  Faceless to Finished account — we&apos;ll link your AppSumo license to it
                  and sign you in. No password needed.
                </p>
                <div className="login-form">
                  <input
                    type="email"
                    autoFocus
                    placeholder="you@email.com"
                    className="login-input"
                    data-testid="redeem-email-input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                  <button
                    type="submit"
                    className="login-cta"
                    data-testid="redeem-submit-btn"
                    disabled={busy || !email}
                  >
                    {busy ? "Activating…" : "Activate my license"}
                  </button>
                  {err && <p className="login-error" data-testid="redeem-error">{err}</p>}
                </div>
              </>
            ) : (
              <>
                <p className="login-sub" data-testid="redeem-no-code">
                  This page activates AppSumo purchases, but no activation code was
                  found in the link. Head to{" "}
                  <a
                    className="login-hero-link"
                    href="https://appsumo.com/account/products/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    AppSumo → My Products
                  </a>{" "}
                  and click your license key to restart activation. Already activated?{" "}
                  <a className="login-hero-link" href="/login">Sign in here</a>.
                </p>
              </>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
