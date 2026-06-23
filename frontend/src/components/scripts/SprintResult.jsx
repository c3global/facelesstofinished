import React, { useState } from "react";
import { ArrowUpRight, ClipboardCopy } from "lucide-react";
import PhoneFrame from "../PhoneFrame";
import ShortPhoneBody from "./ShortPhoneBody";
import { markdownToHtml, copyRichText } from "./SectionCard";

/**
 * SprintResult — renders 5 variant phone frames in a responsive grid.
 * Each variant gets a small header (number, name, angle line, category pill),
 * a "Copy this Short" action that pulls just that variant's raw text to the
 * clipboard, a PhoneFrame containing the parsed HOOK/BODY/CTA beats, and a
 * "Promote to full short" button that re-runs the single-Short pipeline for
 * just that variant's angle.
 */
function variantToClipboardText(v) {
  const header = `# ${(v.name || `Variant ${v.index}`).toUpperCase()}`;
  const angleLine = v.angle ? `Angle: ${v.angle}\n\n` : "";
  return `${header}\n\n${angleLine}${v.body || ""}`.trim();
}

function CopyShortButton({ variant }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="sprint-variant-copy"
      data-testid={`sprint-variant-${variant.index}-copy`}
      onClick={async () => {
        try {
          // Use the rich-HTML clipboard path so B-roll cues paste green
          // into Google Docs / Notion / Word — same UX as Long-form copy.
          // Plain text is preserved as the fallback for editors that
          // strip HTML.
          const text = variantToClipboardText(variant);
          const html = markdownToHtml(text);
          await copyRichText(text, html);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // copyRichText handles its own fallback to writeText. If we
          // reach here, both paths threw — nothing more we can do but
          // skip the "copied" flash so the user re-tries.
        }
      }}
    >
      <ClipboardCopy size={12} />
      {copied ? "Copied!" : "Copy this Short"}
    </button>
  );
}

export default function SprintResult({ variants, platform, onPromote, promotingIndex, onCopyAll }) {
  if (!variants?.length) return null;
  return (
    <div className="sprint-section" data-testid="sprint-section">
      {/* Mirror of the Netlify v1.8.0 header above the sprint grid — a second
          "Copy All N Shorts" button right above the grid in addition to the
          one in the sticky nav, so the action stays visible after the user
          scrolls past the sticky bar. */}
      <div className="sprint-header" data-testid="sprint-header">
        <h3 className="sprint-header-title">Content Sprint</h3>
        <p className="sprint-header-sub">Tap a phone to expand it.</p>
        {onCopyAll && (
          <button
            type="button"
            className="sprint-header-copy-all"
            data-testid="sprint-header-copy-all"
            onClick={onCopyAll}
          >
            <ClipboardCopy size={14} /> Copy all {variants.length} Shorts
          </button>
        )}
      </div>
      <div id="sprint-grid" className="sprint-grid" data-testid="sprint-grid">
        {variants.map((v, i) => {
          // Normalize category for CSS attribute selectors — backend returns
          // values like "how-to" already, but be defensive in case of stray
          // casing or whitespace. CSS rules in App.css key off
          // [data-category="curiosity|contrarian|how-to|story|list"].
          const cat = (v.category || "").toString().trim().toLowerCase().replace(/\s+/g, "-");
          return (
            <div
              key={v.index}
              className="sprint-variant"
              data-testid={`sprint-variant-${v.index}`}
              data-category={cat || undefined}
              // Staggered fade-in matching the SectionCard reveal pattern —
              // 60ms per variant so the grid feels like it's "landing"
              // rather than dumping all five phones in a single frame.
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className="sprint-variant-head">
                <span className="sprint-variant-num">Variant {v.index} / 5</span>
                <span className="sprint-variant-name">{v.name}</span>
                {v.angle && <span className="sprint-variant-angle">{v.angle}</span>}
                {v.category && (
                  <span className="sprint-variant-cat">{v.category}</span>
                )}
              </div>
              <PhoneFrame platform={platform}>
                <ShortPhoneBody shortBody={v.body} />
              </PhoneFrame>
              <div className="sprint-variant-actions">
                <CopyShortButton variant={v} />
                {onPromote && (
                  <button
                    type="button"
                    className="sprint-variant-promote"
                    data-testid={`sprint-variant-${v.index}-promote`}
                    disabled={promotingIndex != null}
                    onClick={() => onPromote(v)}
                  >
                    <ArrowUpRight size={13} />
                    {promotingIndex === v.index
                      ? "Promoting…"
                      : "Promote to full short"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Exported helper so the parent page can implement "Copy All N Shorts" from
// the sticky results nav bar without re-implementing the formatting rules.
export function sprintAllToClipboardText(variants) {
  if (!variants?.length) return "";
  return variants.map(variantToClipboardText).join("\n\n---\n\n");
}
