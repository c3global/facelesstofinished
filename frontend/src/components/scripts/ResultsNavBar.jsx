import React from "react";
import { ArrowDown, ClipboardCopy, ChevronsDownUp, ChevronsUpDown, Plus } from "lucide-react";

/**
 * ResultsNavBar — sticky toolbar that appears at the top of the viewport
 * whenever the Script Engine has produced an output. Mirror of the
 * v1.8.0 release from the live Netlify Script Engine.
 *
 * Props:
 *  - status: short summary string ("Script ready", "Script ready · 5 Shorts", …)
 *  - hasScript: whether the long-form / short-form script section is rendered
 *  - hasShorts: whether the sprint/shorts panel is rendered
 *  - shortsCount: number of shorts (sprint variants) when hasShorts
 *  - allCollapsed: current global collapse state
 *  - onJumpScript / onJumpShorts: anchor scroll handlers
 *  - onCopyScript: copies the full long-form / short package
 *  - onCopyAllShorts: copies every sprint variant concatenated
 *  - onToggleCollapseAll: flips global collapse state
 *  - onStartNew: clears the result and returns to the topic/length picker so
 *    the user can kick off a fresh generation without leaving the current
 *    mode (fixes the "Shorts result + recent history hides the new-short CTA"
 *    trap where you previously had to flip to Long then back to Shorts).
 *  - newCtaLabel: copy for the start-new button ("New short" / "New script").
 */
export default function ResultsNavBar({
  status,
  hasScript,
  hasShorts,
  shortsCount,
  allCollapsed,
  onJumpScript,
  onJumpShorts,
  onCopyScript,
  onCopyAllShorts,
  onToggleCollapseAll,
  onStartNew,
  newCtaLabel = "New script",
}) {
  return (
    <div className="results-nav" data-testid="results-nav">
      <span className="results-nav-status" data-testid="results-nav-status">
        {status}
      </span>
      <div className="results-nav-actions">
        {onStartNew && (
          <button
            type="button"
            className="results-nav-btn is-primary"
            data-testid="results-nav-start-new"
            onClick={onStartNew}
          >
            <Plus size={13} /> {newCtaLabel}
          </button>
        )}
        {hasScript && (
          <button
            type="button"
            className="results-nav-btn"
            data-testid="results-nav-jump-script"
            onClick={onJumpScript}
          >
            <ArrowDown size={13} /> Jump to Script
          </button>
        )}
        {hasShorts && (
          <button
            type="button"
            className="results-nav-btn"
            data-testid="results-nav-jump-shorts"
            onClick={onJumpShorts}
          >
            <ArrowDown size={13} /> Jump to Shorts
          </button>
        )}
        {hasScript && (
          <button
            type="button"
            className="results-nav-btn"
            data-testid="results-nav-copy-script"
            onClick={onCopyScript}
          >
            <ClipboardCopy size={13} /> Copy Script
          </button>
        )}
        {hasShorts && shortsCount > 0 && (
          <button
            type="button"
            className="results-nav-btn"
            data-testid="results-nav-copy-all-shorts"
            onClick={onCopyAllShorts}
          >
            <ClipboardCopy size={13} /> Copy All {shortsCount} Shorts
          </button>
        )}
        <button
          type="button"
          className="results-nav-btn"
          data-testid="results-nav-collapse-toggle"
          onClick={onToggleCollapseAll}
        >
          {allCollapsed ? (
            <>
              <ChevronsUpDown size={13} /> Expand all
            </>
          ) : (
            <>
              <ChevronsDownUp size={13} /> Collapse all
            </>
          )}
        </button>
      </div>
    </div>
  );
}
