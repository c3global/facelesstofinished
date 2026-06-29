import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FileDown } from "lucide-react";

// PDF catalog — URLs pulled directly from the legacy Netlify build
// (/app/legacy_netlify/src/pages/Resources.jsx). The files live on
// filesafe.space CDN; they were never deleted, the page that linked to
// them was just not ported during the Netlify → Emergent migration.
// Restoring the catalog here brings the Resource Library back without
// touching the underlying assets.
const RESOURCES = [
  {
    key: "voiceover",
    number: "01",
    title: "Pitch Perfect AI Voiceover Guide",
    description: "Voice selection, pacing, and delivery techniques for natural-sounding AI narration.",
    file: "https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a2753050de795fc131142a0.pdf",
    accent: "#7F77DD",
  },
  {
    key: "broll",
    number: "02",
    title: "B-Roll Prompt Bank",
    description: "Ready-to-use AI image and video prompts for every shot type in your script.",
    file: "https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a275305f607d4002bd7d862.pdf",
    accent: "#378ADD",
  },
  {
    key: "thumbnail",
    number: "03",
    title: "Thumbnail Kit",
    description: "Click-worthy thumbnail templates, color theory, and composition formulas.",
    file: "https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a275305d91f654725b62870.pdf",
    accent: "#C41A18",
  },
  {
    key: "production",
    number: "04",
    title: "Production Map",
    description: "The 48-hour workflow from idea to upload, with timing for every step.",
    file: "https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a2753050de795fc131142a1.pdf",
    accent: "#1D9E75",
  },
  {
    key: "publishing",
    number: "05",
    title: "Publishing Checklist",
    description: "Titles, tags, descriptions, end screens — everything you need before you hit publish.",
    file: "https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a27530549e55f8519bafdf2.pdf",
    accent: "#C9956C",
  },
];

export default function Resources() {
  return (
    <main className="studio-main scripts-main" data-testid="resources-page">
      {/* Hero — matches the styling rhythm used by Scripts.jsx so the
          Resource Library lands inside the same visual language as the
          rest of the app (eyebrow, large headline, supporting paragraph). */}
      <div className="studio-hero" data-testid="resources-hero">
        <p className="studio-eyebrow">Faceless to Finished · Production Toolkit</p>
        <h1 className="studio-title">
          Everything you need to finish in 48 hours.
        </h1>
        <p className="studio-sub">
          Five guides covering voiceover, B-roll, thumbnails, workflow, and
          publishing. Open any guide in a new tab.
        </p>
        <div style={{ marginTop: 16 }}>
          <Link
            to="/scripts"
            className="saved-angles-toggle"
            data-testid="resources-back-to-scripts"
          >
            <ArrowLeft size={14} /> Back to Script Engine
          </Link>
        </div>
      </div>

      <section
        className="resources-grid"
        data-testid="resources-grid"
        aria-label="Production guides"
      >
        {RESOURCES.map((r) => (
          <a
            key={r.key}
            className="resource-card"
            href={r.file}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`resource-card-${r.key}`}
            style={{ "--card-accent": r.accent }}
          >
            <div
              className="resource-number"
              data-testid={`resource-number-${r.key}`}
            >
              {r.number}
            </div>
            <h3 className="resource-title" data-testid={`resource-title-${r.key}`}>
              {r.title}
            </h3>
            <p className="resource-desc">{r.description}</p>
            <span
              className="resource-open"
              data-testid={`resource-open-${r.key}`}
            >
              <FileDown size={14} /> Open guide
            </span>
          </a>
        ))}
      </section>
    </main>
  );
}
