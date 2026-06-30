import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Sparkles, ListChecks, Lightbulb } from "lucide-react";
import { ROADMAP } from "../data/roadmap.js";

// Public roadmap page at /roadmap. No auth required — AppSumo reviewers
// and prospective buyers can land here straight from the footer link
// without signing in. Data lives in /src/data/roadmap.js so updates are a
// one-file edit (no design changes needed).
//
// Layout mirrors the existing in-app pages: hero block with eyebrow + H1
// + subhead, then four columns of cards. Theme tokens (--bg, --surface,
// --text, --muted, --accent, --warning, --border) auto-switch with the
// dark/light toggle in the header.

const COLUMN_ICONS = {
  shipped: CheckCircle2,
  inProgress: Sparkles,
  planned: ListChecks,
  considering: Lightbulb,
};

function RoadmapColumn({ columnKey, column }) {
  const Icon = COLUMN_ICONS[columnKey] || ListChecks;
  return (
    <section
      className={`roadmap-column roadmap-column-${columnKey}`}
      data-testid={`roadmap-column-${columnKey}`}
    >
      <header className="roadmap-column-head">
        <Icon size={18} strokeWidth={2} aria-hidden />
        <h2 className="roadmap-column-title">{column.label}</h2>
        <span className="roadmap-column-count">{column.items.length}</span>
      </header>
      {column.note && <p className="roadmap-column-note">{column.note}</p>}
      <ul className="roadmap-list">
        {column.items.map((item, i) => (
          <li
            key={`${columnKey}-${i}`}
            className="roadmap-item"
            data-testid={`roadmap-item-${columnKey}-${i}`}
          >
            <div className="roadmap-item-head">
              <h3 className="roadmap-item-title">{item.title}</h3>
              {item.tag && (
                <span className="roadmap-item-tag" data-tag={item.tag.toLowerCase().replace(/\s+/g, "-")}>
                  {item.tag}
                </span>
              )}
            </div>
            <p className="roadmap-item-blurb">{item.blurb}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Roadmap() {
  return (
    <main className="roadmap-main" data-testid="roadmap-page">
      <div className="roadmap-hero">
        <Link to="/" className="roadmap-back" data-testid="roadmap-back-link">
          <ArrowLeft size={14} aria-hidden /> Back to app
        </Link>
        <p className="roadmap-eyebrow" data-testid="roadmap-eyebrow">
          FACELESS TO FINISHED · ROADMAP
        </p>
        <h1 className="roadmap-title" data-testid="roadmap-title">
          What we&rsquo;ve shipped. What&rsquo;s next. What we&rsquo;re hearing.
        </h1>
        <p className="roadmap-sub">
          We update this page in the same change as the code itself — no
          stale promises, no vapor. Want to nudge a &ldquo;Considering&rdquo;
          item into &ldquo;Planned&rdquo;? Email{" "}
          <a className="roadmap-mail" href="mailto:support@c3global.co">
            support@c3global.co
          </a>{" "}
          and tell us why.
        </p>
      </div>

      <div className="roadmap-grid">
        <RoadmapColumn columnKey="shipped" column={ROADMAP.shipped} />
        <RoadmapColumn columnKey="inProgress" column={ROADMAP.inProgress} />
        <RoadmapColumn columnKey="planned" column={ROADMAP.planned} />
        <RoadmapColumn columnKey="considering" column={ROADMAP.considering} />
      </div>

      <div className="roadmap-footnote">
        <p>
          Building a video engine is a marathon, not a sprint. AppSumo
          buyers locked in the lifetime price for everything on this page —
          shipped, in progress, planned. We&rsquo;re building it because
          you bought it.
        </p>
      </div>
    </main>
  );
}
