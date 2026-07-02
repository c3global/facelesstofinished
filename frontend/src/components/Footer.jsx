import React from "react";
import { Link } from "react-router-dom";
import { APP_VERSION, CHANGELOG } from "../changelog.js";

// Site footer — port of the legacy Netlify Footer (/app/legacy_netlify/src/
// Footer.jsx) into the new Emergent app. The version pill is a native
// <details> element that expands inline to show the changelog popup, exactly
// the way it worked on the previous Netlify build. No new dependencies, no
// modal portal — purely CSS-driven.
//
// The footer mounts at the bottom of every authenticated route via App.js.
// Hidden on /login (handled in App.js by checking the pathname).

// Convert "2026-06-29" → "Jun 29, 2026" so the public changelog popup reads
// like a release-notes feed instead of a database dump. Stable across
// locales (we hard-code US format) so the pinned ISO order in changelog.js
// stays the source of truth for sorting.
const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
function humanDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso || "";
  const [, yyyy, mm, dd] = m;
  const monthIdx = parseInt(mm, 10) - 1;
  return `${SHORT_MONTHS[monthIdx] || mm} ${parseInt(dd, 10)}, ${yyyy}`;
}

// localStorage key — bumped to v2 if we ever change the shape. Stores the
// last APP_VERSION the user has expanded the changelog for; any value below
// the current APP_VERSION lights up the amber "What's New" dot on the pill.
const LAST_SEEN_KEY = "f48_changelog_seen_v1";

function readLastSeen() {
  try {
    return localStorage.getItem(LAST_SEEN_KEY) || "";
  } catch {
    return "";
  }
}
function writeLastSeen(v) {
  try {
    localStorage.setItem(LAST_SEEN_KEY, v);
  } catch {
    /* localStorage disabled / private mode — silently skip */
  }
}

export default function Footer() {
  // Track "has the user seen this release" so we can show the amber dot.
  // Initial state reads from localStorage; on first-ever visit it's empty
  // string, which evaluates as < APP_VERSION → dot shows. The dot dismisses
  // as soon as the user clicks the pill (handled in onToggle).
  const [lastSeen, setLastSeen] = React.useState(() => readLastSeen());
  const hasUnseenRelease = lastSeen !== APP_VERSION;

  const handleToggle = (e) => {
    // <details> fires onToggle for both expand AND collapse. We only want
    // to mark "seen" when the user EXPANDS it (open=true) — that's when
    // they actually saw the new entries.
    if (e.currentTarget.open && lastSeen !== APP_VERSION) {
      setLastSeen(APP_VERSION);
      writeLastSeen(APP_VERSION);
    }
  };

  return (
    <footer className="site-footer" data-testid="site-footer">
      <img
        className="footer-mark"
        src="/favicon.png"
        alt="Faceless 48"
        data-testid="footer-mark"
      />
      <div className="footer-text">
        <div className="footer-line">
          <span data-testid="footer-copyright">© 2026 C3 Global</span>
          <Link
            to="/redeem"
            className="footer-link"
            data-testid="footer-redeem-link"
          >
            Have a redemption code?
          </Link>
          <Link
            to="/roadmap"
            className="footer-link"
            data-testid="footer-roadmap-link"
          >
            Roadmap
          </Link>
          <details
            className="footer-changelog"
            data-testid="footer-changelog"
            onToggle={handleToggle}
          >
            <summary
              className={`footer-version ${hasUnseenRelease ? "has-unseen" : ""}`}
              data-testid="footer-version"
              data-unseen={hasUnseenRelease ? "1" : "0"}
            >
              v{APP_VERSION}
              {hasUnseenRelease && (
                <span
                  className="footer-version-dot"
                  data-testid="footer-version-dot"
                  aria-label="New release available"
                />
              )}
            </summary>
            <div
              className="footer-changelog-panel"
              data-testid="footer-changelog-panel"
            >
              <h4>What&apos;s New</h4>
              {CHANGELOG.map((entry) => (
                <div
                  key={entry.version}
                  className="footer-changelog-entry"
                  data-testid={`footer-changelog-entry-${entry.version}`}
                >
                  <div className="footer-changelog-head">
                    <strong>v{entry.version}</strong>
                    <span className="footer-changelog-date">{humanDate(entry.date)}</span>
                  </div>
                  <ul>
                    {entry.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </details>
        </div>
      </div>
    </footer>
  );
}
