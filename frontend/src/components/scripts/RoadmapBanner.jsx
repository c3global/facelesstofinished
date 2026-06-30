import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Sparkles, X, ArrowRight } from "lucide-react";
import { APP_VERSION } from "../../changelog.js";

// One-shot release banner on the Scripts page. Tells buyers a new version
// shipped + points them at the public Roadmap. Dismissable per version —
// once Charity bumps APP_VERSION again, every buyer sees a new banner
// once and only once for that release.
//
// Storage: localStorage key `f48_roadmap_banner_dismissed_v{APP_VERSION}`.
// Switching versions resets the dismissal state implicitly (different key).
const STORAGE_KEY = `f48_roadmap_banner_dismissed_v${APP_VERSION}`;

export default function RoadmapBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    try {
      const dismissed = localStorage.getItem(STORAGE_KEY) === "1";
      if (!dismissed) setShow(true);
    } catch {
      setShow(true); // fall back to showing it if storage is blocked
    }
  }, []);

  const dismiss = () => {
    setShow(false);
    try { localStorage.setItem(STORAGE_KEY, "1"); } catch { /* storage blocked — banner is gone for this tab anyway */ }
  };

  if (!show) return null;

  return (
    <div className="roadmap-banner" data-testid="scripts-roadmap-banner" role="region" aria-label="New release announcement">
      <Sparkles size={14} className="roadmap-banner-icon" aria-hidden />
      <div className="roadmap-banner-body">
        <strong className="roadmap-banner-title">v{APP_VERSION} just shipped.</strong>
        <span className="roadmap-banner-sub">
          {" "}See what&rsquo;s new and what&rsquo;s coming next on the public roadmap.
        </span>
      </div>
      <Link
        to="/roadmap"
        className="roadmap-banner-cta"
        data-testid="scripts-roadmap-banner-cta"
      >
        View roadmap <ArrowRight size={12} />
      </Link>
      <button
        type="button"
        className="roadmap-banner-dismiss"
        data-testid="scripts-roadmap-banner-dismiss"
        onClick={dismiss}
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}
