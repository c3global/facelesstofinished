import React from "react";
import { Clapperboard, UserCircle2, Film, Layers } from "lucide-react";

// Single source of truth for Composite's "coming soon" status — used both
// for the visible badge text on the card AND the toast that fires when a
// user taps it. Keeping the two strings in lockstep here so a future tweak
// of one doesn't drift from the other.
export const COMPOSITE_BADGE = "Rolling Out";
export const COMPOSITE_TOAST =
  "Composite mode is rolling out — Avatar + B-roll cutaways are in Phase 3. Pick Avatar or Faceless for now.";

/**
 * ModePicker — first-visit landing card on /studio.
 *
 * Three cards (Avatar / Faceless / Composite). Composite is rolling out as
 * Phase 3 and is wired but disabled with a "Rolling Out" badge so users see
 * it's coming. Selection is persisted via the parent so returning users skip
 * straight to the chip-form on subsequent visits; a "Change mode" link lets
 * them re-open the picker any time.
 *
 * Brand-token usage: cards tint with canonical palette —
 *   Avatar   → --accent  (#7F77DD primary purple)
 *   Faceless → --success (#1D9E75 teal)
 *   Composite→ --warning (#C9956C warm rose)
 */
export default function ModePicker({ onPick, onComingSoon }) {
  const cards = [
    {
      id: "avatar",
      Icon: UserCircle2,
      title: "Avatar",
      blurb: "On-camera presenters with AI avatars and natural voice.",
      tint: "var(--accent)",
      testid: "mode-picker-avatar",
    },
    {
      id: "faceless",
      Icon: Film,
      title: "Faceless",
      blurb: "Professional B-roll with AI voiceover and cinematic visuals.",
      tint: "var(--success)",
      testid: "mode-picker-faceless",
    },
    {
      id: "composite",
      Icon: Layers,
      title: "Composite",
      blurb: "Avatar + B-roll combined for maximum impact.",
      tint: "var(--warning)",
      badge: COMPOSITE_BADGE,
      disabled: true,
      testid: "mode-picker-composite",
    },
  ];

  return (
    <section className="mode-picker" data-testid="mode-picker">
      <div className="mode-picker-header">
        <Clapperboard size={42} className="mode-picker-icon" aria-hidden="true" />
        <h1 className="mode-picker-title">Choose Your Video Creation Mode</h1>
        <p className="mode-picker-sub">Pick the workflow that fits your content style.</p>
      </div>
      <div className="mode-picker-grid">
        {cards.map((c) => (
          <button
            key={c.id}
            type="button"
            className={`mode-picker-card ${c.disabled ? "is-coming-soon" : ""}`}
            data-mode={c.id}
            data-testid={c.testid}
            // a11y — pick a clean spoken label so screen readers announce
            // "Select Avatar mode" rather than the entire blurb sentence.
            aria-label={c.disabled ? `${c.title} mode (${c.badge})` : `Select ${c.title} mode`}
            style={{ "--mode-tint": c.tint }}
            onClick={() => {
              if (c.disabled) onComingSoon?.(c.id);
              else onPick?.(c.id);
            }}
          >
            <div className="mode-picker-art" aria-hidden="true">
              <c.Icon size={84} strokeWidth={1.25} />
            </div>
            <div className="mode-picker-art-icon" aria-hidden="true">
              <c.Icon size={18} strokeWidth={2} />
            </div>
            {c.badge && (
              <span className="mode-picker-badge" data-testid={`${c.testid}-badge`}>
                {c.badge}
              </span>
            )}
            <h2 className="mode-picker-card-title">{c.title}</h2>
            <p className="mode-picker-card-blurb">{c.blurb}</p>
            <span className="mode-picker-card-cta">
              {c.disabled ? "Coming soon" : "Select"}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
