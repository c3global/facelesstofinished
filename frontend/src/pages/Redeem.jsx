import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { KeyRound, CheckCircle2, ArrowRight } from "lucide-react";
import { apiClient, useAuth } from "../App";

/**
 * Code redemption page. Single-purpose, reachable from three entry points
 * (footer link, login toggle, profile dropdown) — but always lands here.
 * Deliberately generic: no "AppSumo" branding visible. Accepts any code
 * format the backend's normalizer can parse (current format = AppSumo's
 * default, but partner / agency / beta codes route here too).
 *
 * Flow:
 *   - Signed in: paste code → POST /api/licenses/redeem → land in Studio.
 *   - Not signed in: send to /login?redeem=<code> so they auth first, then
 *     auto-replay the redemption.
 *   - AppSumo OAuth redirect: arrives with ?code= (or ?appsumo_code= via
 *     the backend's /api/appsumo/oauth/redirect hop). Signed-in users get
 *     it exchanged automatically via POST /api/licenses/redeem-oauth; new
 *     buyers are bounced to /login where the code rides along with the
 *     magic-link request and is applied server-side after email proof.
 */
export default function Redeem() {
  const { user, loading, refresh } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const oauthCode = useMemo(
    () => (params.get("appsumo_code") || params.get("code") || "").trim(),
    [params],
  );
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(null);

  // AppSumo OAuth arrival — auto-activate once auth state is known.
  useEffect(() => {
    if (!oauthCode || loading || success) return;
    if (!user) {
      // New buyer: the OAuth code rides along with the magic-link request
      // (Login reads this stash) and is redeemed server-side after the
      // email is proven. It's single-use, so it must not be burned here.
      try { localStorage.setItem("f48_pending_redeem_oauth", oauthCode); } catch {}
      nav(`/login?appsumo_oauth=${encodeURIComponent(oauthCode)}`, { replace: true });
      return;
    }
    let cancelled = false;
    (async () => {
      setSubmitting(true);
      setError("");
      try {
        const r = await apiClient.post("/licenses/redeem-oauth", { code: oauthCode });
        if (cancelled) return;
        setSuccess(r.data);
        try { localStorage.removeItem("f48_pending_redeem_oauth"); } catch {}
        try { await refresh?.(); } catch {}
      } catch (e) {
        if (cancelled) return;
        const detail = e?.response?.data?.detail;
        setError(typeof detail === "string" ? detail : (detail?.message || "Couldn't activate your AppSumo purchase."));
      } finally {
        if (!cancelled) setSubmitting(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oauthCode, user, loading]);

  const trimmed = code.trim();
  const canSubmit = trimmed.length >= 6 && !submitting && !success;

  const onSubmit = async (e) => {
    e?.preventDefault?.();
    if (!canSubmit) return;
    setError("");
    setSubmitting(true);
    try {
      if (!user) {
        // Pre-auth: stash and bounce to login. Login completes, replays.
        try { localStorage.setItem("f48_pending_redeem", trimmed); } catch {}
        nav(`/login?redeem=${encodeURIComponent(trimmed)}`);
        return;
      }
      const r = await apiClient.post("/licenses/redeem", { code: trimmed });
      setSuccess(r.data);
      try { localStorage.removeItem("f48_pending_redeem"); } catch {}
      // Refresh user/entitlements so the Header's tier label updates.
      try { await refresh?.(); } catch {}
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : (detail?.message || e?.message || "Couldn't redeem that code."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="redeem-main" data-testid="redeem-page">
      <div className="redeem-card">
        <div className="redeem-icon" aria-hidden="true">
          <KeyRound size={26} />
        </div>
        <h1 className="redeem-title">Redeem your code</h1>
        <p className="redeem-sub">
          Paste the code from your purchase email and we'll unlock your plan instantly.
        </p>

        {success ? (
          <div className="redeem-success" data-testid="redeem-success" role="status">
            <CheckCircle2 size={22} />
            <div>
              <strong>You're on {success.tier_label}.</strong>
              <p>{success.message}</p>
            </div>
            <button
              type="button"
              className="redeem-go-btn"
              onClick={() => nav("/scripts")}
              data-testid="redeem-go-app"
            >
              Open your dashboard <ArrowRight size={14} />
            </button>
          </div>
        ) : oauthCode && submitting ? (
          <p className="redeem-sub" data-testid="redeem-oauth-activating" role="status">
            Activating your purchase…
          </p>
        ) : (
          <form onSubmit={onSubmit} className="redeem-form">
            <label className="redeem-label" htmlFor="redeem-input">
              Your code
            </label>
            <input
              id="redeem-input"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              data-testid="redeem-input"
              disabled={submitting}
            />
            {error && (
              <div className="redeem-error" data-testid="redeem-error" role="alert">
                {error}
              </div>
            )}
            <button
              type="submit"
              className="redeem-submit-btn"
              disabled={!canSubmit}
              data-testid="redeem-submit"
            >
              {submitting ? "Redeeming…" : user ? "Unlock my plan" : "Continue to sign in"}
            </button>
          </form>
        )}

        <div className="redeem-foot">
          <Link to={user ? "/scripts" : "/login"} className="redeem-foot-link">
            Don't have a code? {user ? "Back to your dashboard" : "Just sign in"}
          </Link>
        </div>
      </div>
    </main>
  );
}
