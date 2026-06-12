import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

// Stage rotation table per mode. Each label sits ~7s before advancing.
// On a 25-40s real Claude response this typically advances 4-5 times.
const STAGES = {
  long: [
    "Brainstorming the angle",
    "Drafting video concept",
    "Writing hook variations",
    "Building outline",
    "Writing full narration",
    "Stitching transitions",
    "Compiling B-roll shot list",
    "Adding production notes",
  ],
  shorts: [
    "Locking the angle",
    "Writing hook variations",
    "Drafting hook / body / CTA",
    "Layering on-screen cues",
    "Compiling B-roll shot list",
    "Writing caption + hashtags",
    "Designing thumbnail variants",
  ],
  sprint: [
    "Plotting 5 distinct angles",
    "Drafting Variant 1",
    "Drafting Variant 2",
    "Drafting Variant 3",
    "Drafting Variant 4",
    "Drafting Variant 5",
    "Final pass + polish",
  ],
};

const STAGE_DURATION_MS = 7000;

/**
 * GenProgress — animated progress bar + rotating stage label shown during
 * a long-running Claude generation. The bar itself is a CSS-only indeterminate
 * shuttle (see .gen-progress-fill). The label rotates through stage strings
 * every STAGE_DURATION_MS so the user gets the feel of streaming progress.
 */
export default function GenProgress({ mode = "long", elapsed = 0 }) {
  const stages = STAGES[mode] || STAGES.long;
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (idx >= stages.length - 1) return;
    const t = setTimeout(() => setIdx((i) => Math.min(i + 1, stages.length - 1)), STAGE_DURATION_MS);
    return () => clearTimeout(t);
  }, [idx, stages.length]);

  return (
    <div className="gen-progress" data-testid="gen-progress">
      <div className="gen-progress-row">
        <span className="gen-progress-label" data-testid="gen-progress-label">
          <Loader2 size={13} className="spin" /> {stages[idx]}…
        </span>
        <span className="gen-progress-elapsed">{elapsed}s</span>
      </div>
      <div className="gen-progress-bar" role="progressbar" aria-label={stages[idx]}>
        <div className="gen-progress-fill" />
      </div>
    </div>
  );
}
