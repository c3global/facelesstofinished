import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { CHANGELOG, APP_VERSION } from "../changelog.js";

// Public changelog page at /changelog. Reads from the same `changelog.js`
// file the in-app footer popup uses, so the two views never drift.
// No auth required — AppSumo reviewers landing here see a transparent
// shipping history without signing up.

export default function Changelog() {
  return (
    <main className="changelog-main" data-testid="changelog-page">
      <div className="changelog-hero">
        <Link to="/" className="roadmap-back" data-testid="changelog-back-link">
          <ArrowLeft size={14} aria-hidden /> Back to app
        </Link>
        <p className="roadmap-eyebrow" data-testid="changelog-eyebrow">
          FACELESS TO FINISHED · CHANGELOG
        </p>
        <h1 className="roadmap-title" data-testid="changelog-title">
          Every shipping change, in plain English.
        </h1>
        <p className="roadmap-sub">
          Currently on <b>v{APP_VERSION}</b>. We update this file in the same
          deploy as the code, so the gap between &ldquo;released&rdquo; and
          &ldquo;documented&rdquo; is zero.
        </p>
      </div>

      <ol className="changelog-timeline" data-testid="changelog-timeline">
        {CHANGELOG.map((entry, i) => (
          <li key={entry.version} className="changelog-entry" data-testid={`changelog-entry-${entry.version}`}>
            <div className="changelog-marker" aria-hidden />
            <div className="changelog-body">
              <header className="changelog-entry-head">
                <h2 className="changelog-version">v{entry.version}</h2>
                <time className="changelog-date">{entry.date}</time>
                {i === 0 && <span className="changelog-latest-pill">Latest</span>}
              </header>
              <ul className="changelog-changes">
                {entry.changes.map((c, idx) => (
                  <li key={idx}>{c}</li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ol>
    </main>
  );
}
