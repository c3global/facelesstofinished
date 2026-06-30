// Stable script-engine constants + small pure helpers. Extracted from
// pages/Scripts.jsx in v1.15.0 so the main page module focuses on flow
// orchestration. Everything here is data + pure functions — no hooks,
// no JSX. Imported by Scripts.jsx and (eventually) by sibling Script
// preview / settings pages.

export const MODES = { LONG: "long", SHORTS: "shorts" };

export const STEPS = {
  TOPIC: "topic",
  ANGLES: "angles",
  GENERATING: "generating",
  RESULT: "result",
};

export const LENGTHS = [
  { id: "short",  label: "Short",  desc: "5–8 min · 800–1,200 words" },
  { id: "medium", label: "Medium", desc: "10–15 min · 1,500–2,200 words" },
  { id: "long",   label: "Long",   desc: "18–25 min · 2,700–3,800 words" },
];

export const PLATFORMS = [
  { id: "youtube", label: "YouTube Shorts", accent: "#FF0033" },
  { id: "reels",   label: "Instagram Reels", accent: "#E1306C" },
  // TikTok's brand cyan is so light that white text disappears on it.
  // The contrast fix lives in App.css via [data-platform="tiktok"] →
  // --platform-fg: #0B1A1A.
  { id: "tiktok",  label: "TikTok",          accent: "#25F4EE" },
];

export const TAGLINES = [
  "Write a script that gets watched.",
  "Type a topic. Get a complete script.",
  "From blank page to ready-to-record — in seconds.",
];

// Stable key used to dedupe + identify saved angles across DB + local state.
export const angleKey = (a) =>
  `${(a?.name || "").toLowerCase()}::${(a?.framing || "").toLowerCase()}`;

// Ordered map of section headers Claude emits → friendly status text.
// Used by the drip-banner to show "Writing hook variations…" etc. while
// streaming. The LATEST header found in the partial text wins.
export const LONG_PHASES = [
  ["VIDEO CONCEPT",         "Drafting video concept…"],
  ["HOOK VARIATIONS",       "Writing hook variations…"],
  ["OUTLINE",               "Building outline…"],
  ["FULL NARRATION SCRIPT", "Writing narration…"],
  ["TRANSITIONS",           "Composing transitions…"],
  ["B-ROLL SHOT LIST",      "Compiling B-roll shot list…"],
  ["PRODUCTION NOTES",      "Adding production notes…"],
];
export const SHORTS_PHASES = [
  ["HOOK",             "Drafting hook…"],
  ["SCRIPT",           "Writing the short…"],
  ["CAPTION",          "Generating caption…"],
  ["HASHTAGS",         "Picking hashtags…"],
  ["B-ROLL",           "Listing B-roll…"],
  ["PRODUCTION NOTES", "Adding production notes…"],
];
export const SPRINT_PHASES = [
  ["VARIANT 1", "Drafting variant 1 of 5…"],
  ["VARIANT 2", "Drafting variant 2 of 5…"],
  ["VARIANT 3", "Drafting variant 3 of 5…"],
  ["VARIANT 4", "Drafting variant 4 of 5…"],
  ["VARIANT 5", "Drafting variant 5 of 5…"],
];

/**
 * Given the partial streaming text, return a friendly phase label by
 * scanning for the LATEST section header that's appeared so far. Falls
 * back to "Thinking…" before any header lands.
 */
export function currentStreamingPhase(text, mode) {
  if (!text) return "Thinking…";
  const phases =
    mode === "sprint" ? SPRINT_PHASES :
    mode === "shorts" ? SHORTS_PHASES :
    LONG_PHASES;
  let lastMatch = phases[0][1];
  const upper = text.toUpperCase();
  for (const [header, label] of phases) {
    if (upper.includes(header)) lastMatch = label;
  }
  return lastMatch;
}
