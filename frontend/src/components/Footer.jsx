import React from "react";
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

export default function Footer() {
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
          <details className="footer-changelog" data-testid="footer-changelog">
            <summary
              className="footer-version"
              data-testid="footer-version"
            >
              v{APP_VERSION}
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
