import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate, Link } from "react-router-dom";
import { Zap, Mic, Film, ArrowRight, KeyRound, Mail, CheckCircle2 } from "lucide-react";
import { apiClient, useAuth } from "../App";

// Sign-in page — magic-link only.
//
// v1.19.0 (P0 security fix) — the previous "type email → immediately
// signed in" flow was replaced with a real passwordless email loop.
// User enters email → backend generates a single-use token, pushes it
// to Charity's GHL workflow (which sends the actual email), then the
// user clicks the link in their inbox and lands on /auth/callback with
// a fresh JWT in the URL fragment.
//
// Anti-enumeration: the backend ALWAYS returns success, so we never
// reveal which addresses are on file. Users just see "check your email."
export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [pendingRedeem, setPendingRedeem] = useState("");
  const [pendingOauth, setPendingOauth] = useState("");

  // Detect returning customers from the durable localStorage flag.
  const isReturning = useMemo(() => {
    try { return localStorage.getItem("f48_studio_returning") === "1"; }
    catch { return false; }
  }, []);

  // Surface any error the /auth/callback page bounced back (expired
  // link, no access, missing token).
  useEffect(() => {
    const cb = params.get("err");
    if (!cb) return;
    const map = {
      expired_or_invalid_link: "That sign-in link expired or was already used. Request a new one below.",
      no_access_for_this_email: "We couldn't find an active F2F48 account for that email. Contact support@c3global.co if you think this is wrong.",
      missing_token: "The sign-in link didn't include a valid token. Request a fresh one below.",
      verify_failed: "We couldn't complete sign-in. Try requesting a new link.",
      code_invalid: "We couldn't apply your code — it may have expired or already been used. Restart activation from AppSumo → My Products, or contact support@c3global.co.",
    };
    setErr(map[cb] || "Something went wrong. Try requesting a new sign-in link.");
  }, [params]);

  // If the user got bounced here from /redeem, keep the pending code so
  // they can pick up where they left off after signing in via the link.
  // Two flavors: a pasted code/license key (redeem) and the single-use
  // AppSumo OAuth code (appsumo_oauth). Both ride along with the magic-link
  // request and are applied server-side after the email is proven.
  useEffect(() => {
    const urlCode = params.get("redeem");
    let stash = "";
    try { stash = localStorage.getItem("f48_pending_redeem") || ""; } catch { /* ignored */ }
    const code = (urlCode || stash || "").trim();
    if (code) setPendingRedeem(code);

    const urlOauth = params.get("appsumo_oauth");
    let oauthStash = "";
    try { oauthStash = localStorage.getItem("f48_pending_redeem_oauth") || ""; } catch { /* ignored */ }
    const oauth = (urlOauth || oauthStash || "").trim();
    if (oauth) setPendingOauth(oauth);
  }, [params]);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const trimmed = email.trim();

      // Admin / DEV_BYPASS fast lane. Try /auth/check first — the backend
      // will short-circuit only for ADMIN_EMAILS + DEV_BYPASS_EMAIL and
      // return a fresh JWT on the spot. Any other email gets 403 and
      // falls through to the magic-link flow below.
      // If a redemption code is pending, we still want it applied
      // during real activation, so we skip the bypass and force the
      // magic-link path (which carries the code server-side).
      if (!pendingRedeem && !pendingOauth) {
        try {
          await login(trimmed);
          // Navigate directly to /scripts (skipping "/" → /scripts
          // redirect chain) so RequireAuth doesn't race the setUser
          // commit and bounce us back to /login.
          navigate("/scripts", { replace: true });
          return;
        } catch (bypassErr) {
          const status = bypassErr?.response?.status;
          // Anything other than 403 (magic-link required) is a real
          // problem — surface it. 403 falls through to magic-link.
          if (status && status !== 403) {
            const msg =
              bypassErr?.response?.data?.detail ||
              "We couldn't sign you in. Try again.";
            setErr(typeof msg === "string" ? msg : JSON.stringify(msg));
            return;
          }
        }
      }

      const body = { email: trimmed };
      if (pendingRedeem) body.redeem = pendingRedeem;
      else if (pendingOauth) body.appsumo_oauth = pendingOauth;
      await apiClient.post("/auth/request-magic-link", body);
      // Persist a returning flag now (before they even click the link)
      // so the next visit renders "Welcome back" copy.
      try { localStorage.setItem("f48_studio_returning", "1"); } catch { /* ignored */ }
      setSent(true);
    } catch (e2) {
      const msg = e2?.response?.data?.detail || "We couldn't send the link. Check your email address and try again.";
      setErr(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setBusy(false);
    }
  };

  const resend = () => {
    setSent(false);
    setErr("");
  };

  return (
    <div className="login-wrap" data-testid="login-page">
      <div className="login-stack">
        <div className="login-hero-image-wrap" data-testid="login-hero-image-wrap">
          <img
            className="login-hero-image"
            src={`${process.env.PUBLIC_URL || ""}/login-hero.png`}
            alt="Faceless to Finished Studio across desktop, laptop, tablet and mobile"
            data-testid="login-hero-image"
          />
        </div>

        <div className="login-grid">
          <section className="login-hero" data-testid="login-hero">
            <p className="login-hero-eyebrow">Faceless to Finished</p>
            <h1 className="login-hero-headline">
              Hit publish <span className="login-hero-accent">10× faster.</span>
            </h1>
            <p className="login-hero-sub">
              AI-assisted scripts, avatar videos, and faceless renders — purpose-built
              for Faceless to Finished customers. Sign in with the email you purchased
              with to access the Studio.
            </p>

            <ul className="login-hero-features">
              <li className="login-hero-feature">
                <span className="login-hero-feature-icon"><Zap size={16} /></span>
                <div>
                  <div className="login-hero-feature-title">Script Engine</div>
                  <div className="login-hero-feature-sub">Long-form + Shorts with topic-angle AI.</div>
                </div>
              </li>
              <li className="login-hero-feature">
                <span className="login-hero-feature-icon"><Mic size={16} /></span>
                <div>
                  <div className="login-hero-feature-title">Avatar Studio</div>
                  <div className="login-hero-feature-sub">1,200+ HeyGen avatars and 2,300+ voices.</div>
                </div>
              </li>
              <li className="login-hero-feature">
                <span className="login-hero-feature-icon"><Film size={16} /></span>
                <div>
                  <div className="login-hero-feature-title">Faceless Render</div>
                  <div className="login-hero-feature-sub">Stock B-roll + voiceover, stitched and shipped.</div>
                </div>
              </li>
            </ul>

            <p className="login-hero-cta-note">
              New to Faceless to Finished?{" "}
              <a
                className="login-hero-link"
                href="https://sprint.c3global.co/faceless"
                target="_blank"
                rel="noopener noreferrer"
                data-testid="login-hero-learn-more"
              >
                Learn more <ArrowRight size={12} />
              </a>
            </p>
          </section>

          {sent ? (
            <div className="login-card login-card-sent" data-testid="login-sent-card">
              <p className="login-eyebrow">Check your inbox</p>
              <div className="login-sent-icon" aria-hidden="true">
                <CheckCircle2 size={44} />
              </div>
              <h2 className="login-title" data-testid="login-sent-title">
                Link sent.
              </h2>
              <p className="login-sub">
                If <b data-testid="login-sent-email">{email}</b> is on our list, we just emailed you a secure sign-in link.
                It expires in 15 minutes. Open it on this device to enter the Studio.
              </p>
              <ul className="login-sent-hints">
                <li>Didn&apos;t get the email? Check spam or promotions.</li>
                <li>Wrong email? Use a different address below.</li>
              </ul>
              <button
                type="button"
                className="login-cta login-cta-secondary"
                onClick={resend}
                data-testid="login-resend-btn"
              >
                Send another link
              </button>
              {pendingRedeem && (
                <div className="login-pending-redeem" data-testid="login-pending-redeem">
                  <KeyRound size={13} />
                  <span>Your redemption code <b>{pendingRedeem}</b> will be applied automatically after sign-in.</span>
                </div>
              )}
            </div>
          ) : (
            <form className="login-card" onSubmit={submit} data-testid="login-form">
              <p className="login-eyebrow">Studio Access</p>
              <h2 className="login-title" data-testid="login-title">
                {pendingRedeem ? "Sign in to redeem." : isReturning ? "Welcome back." : "Sign in."}
              </h2>
              <p className="login-sub">
                {pendingRedeem
                  ? "Enter your email and we'll send you a secure sign-in link. Your code will apply automatically after sign-in."
                  : isReturning
                  ? "Enter your email and we'll send a fresh sign-in link to your inbox."
                  : "Passwordless sign-in — use the email you purchased Faceless to Finished with. We'll email you a one-time secure link."}
              </p>
              {pendingRedeem && (
                <div className="login-pending-redeem" data-testid="login-pending-redeem">
                  <KeyRound size={13} />
                  <span>Code: <b>{pendingRedeem}</b></span>
                </div>
              )}
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
                  <Mail size={15} />
                  {busy ? "Sending link…" : "Email me a sign-in link"}
                </button>
                {err && <p className="login-error" data-testid="login-error">{err}</p>}
                {!pendingRedeem && (
                  <Link
                    to="/redeem"
                    className="login-redeem-toggle"
                    data-testid="login-redeem-toggle"
                  >
                    <KeyRound size={12} /> I have a redemption code instead
                  </Link>
                )}
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
