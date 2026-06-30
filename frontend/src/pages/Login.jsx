import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { Zap, Mic, Film, ArrowRight, KeyRound } from "lucide-react";
import { useAuth, apiClient } from "../App";

// Brief landing-feel sign-in page. Two columns on desktop, stacked on
// mobile. The left column gives non-customers enough context to know
// what F2F48 Studio is (so they don't feel mis-routed when they don't
// have access). The right column is the existing sign-in card with copy
// that switches between first-time visitor and returning-customer based
// on the `f48_studio_returning` flag set in App.js#login().
export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingRedeem, setPendingRedeem] = useState("");

  // Detect returning customers from the durable localStorage flag. Falls
  // back to false on first paint (SSR-safe in case we ever ship one).
  const isReturning = useMemo(() => {
    try { return localStorage.getItem("f48_studio_returning") === "1"; }
    catch { return false; }
  }, []);

  // If the user got bounced here from /redeem (because they weren't signed
  // in yet), the code is in either ?redeem=… or localStorage. Pick it up
  // and replay after a successful sign-in. Mirrors the "deep link continue"
  // pattern from Stripe checkout success flows.
  useEffect(() => {
    const urlCode = params.get("redeem");
    let stash = "";
    try { stash = localStorage.getItem("f48_pending_redeem") || ""; } catch {}
    const code = (urlCode || stash || "").trim();
    if (code) setPendingRedeem(code);
  }, [params]);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const { welcome } = await login(email.trim());
      // Stash the optional welcome payload (set on first sign-in after a
      // Pinball auto-grant) so the Scripts page can fire a one-shot toast
      // once it mounts. sessionStorage > localStorage here so the toast
      // doesn't keep firing across browser sessions.
      if (welcome) {
        try {
          sessionStorage.setItem("f48_pending_welcome", JSON.stringify(welcome));
        } catch {}
      }

      // Replay a deferred redemption now that auth is established. If it
      // succeeds the user lands on /redeem and sees the success state;
      // failures still navigate to /redeem so the error message renders
      // in context rather than as a silent failure.
      if (pendingRedeem) {
        try {
          await apiClient.post("/licenses/redeem", { code: pendingRedeem });
        } catch { /* surface on /redeem */ }
        try { localStorage.removeItem("f48_pending_redeem"); } catch {}
        nav(`/redeem?code=${encodeURIComponent(pendingRedeem)}`);
        return;
      }

      // Default landing on the Script Engine — Studio access is gated and
      // many customers only purchased Faceless to Finished (no Studio).
      nav("/scripts");
    } catch (e) {
      const msg = e?.response?.data?.detail || "Could not sign in. Use the email you bought with.";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap" data-testid="login-page">
      {/* Minimal landing nav — visible to non-signed-in visitors and
          AppSumo reviewers so they can browse the roadmap + changelog
          before committing to an account. Three links only; pricing /
          features intentionally NOT here (the login hero handles that). */}
      <nav className="login-topnav" data-testid="login-topnav" aria-label="Public navigation">
        <span className="login-topnav-brand" data-testid="login-topnav-brand">
          Faceless to Finished
        </span>
        <div className="login-topnav-links">
          <Link to="/roadmap" className="login-topnav-link" data-testid="login-topnav-roadmap">
            Roadmap
          </Link>
          <Link to="/changelog" className="login-topnav-link" data-testid="login-topnav-changelog">
            Changelog
          </Link>
          <a
            className="login-topnav-link"
            href="#login"
            data-testid="login-topnav-signin"
            onClick={(e) => {
              e.preventDefault();
              document.querySelector("[data-testid='login-form']")?.scrollIntoView({ behavior: "smooth" });
              document.querySelector("[data-testid='login-email-input']")?.focus();
            }}
          >
            Sign in
          </a>
        </div>
      </nav>
      <div className="login-stack">
        {/* Top: full-width centered hero image. Sits ABOVE the 2-col grid
            so it visually anchors the page; the text + sign-in form sit
            side-by-side on the same vertical level beneath it. */}
        <div className="login-hero-image-wrap" data-testid="login-hero-image-wrap">
          <img
            className="login-hero-image"
            src={`${process.env.PUBLIC_URL || ""}/login-hero.png`}
            alt="Faceless to Finished Studio across desktop, laptop, tablet and mobile"
            data-testid="login-hero-image"
          />
        </div>

        <div className="login-grid">
          {/* Brief landing hero text — left column */}
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

        {/* Sign-in card */}
        <form className="login-card" onSubmit={submit} data-testid="login-form">
          <p className="login-eyebrow">Studio Access</p>
          <h2 className="login-title" data-testid="login-title">
            {pendingRedeem ? "Sign in to redeem." : isReturning ? "Welcome back." : "Sign in."}
          </h2>
          <p className="login-sub">
            {pendingRedeem
              ? "Sign in with your email and we'll apply your code automatically."
              : isReturning
              ? "Enter your email to jump back into the Studio."
              : "Use the email you purchased Faceless to Finished with — no password needed."}
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
              {busy ? "Signing in…" : pendingRedeem ? "Sign in & redeem" : "Enter Studio"}
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
        </div>
      </div>
    </div>
  );
}
