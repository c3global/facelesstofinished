// Parse the script-engine markdown output into named sections keyed by ### header.
// Ported from the legacy Netlify parser.

export function parseSections(raw) {
  if (!raw) return {};
  const lines = raw.split("\n");
  const sections = {};
  let current = null;
  let buffer = [];

  const flush = () => {
    if (current) sections[current.key] = { title: current.title, body: buffer.join("\n").trim() };
    buffer = [];
  };

  for (const line of lines) {
    const m = line.match(/^###\s+(.*)$/);
    if (m) {
      flush();
      const title = m[1].trim();
      current = { key: classify(title), title };
    } else if (current) {
      buffer.push(line);
    }
  }
  flush();
  return sections;
}

function classify(title) {
  const t = title.toUpperCase();
  if (t.includes("SHORT-FORM SCRIPT") || t.includes("SHORT FORM SCRIPT")) return "shortScript";
  if (t.includes("ON-SCREEN TEXT") || t.includes("ON SCREEN TEXT")) return "onScreen";
  if (t.includes("CAPTION")) return "caption";
  if (t.includes("HASHTAG")) return "hashtags";
  if (t.includes("COVER IMAGE") || t.includes("COVER PROMPT")) return "coverPrompts";
  if (t.includes("TITLE") || t.includes("THUMBNAIL")) return "titleVariants";
  if (t.includes("TOPIC ANGLE")) return "angles";
  if (t.includes("HOOK VARIATION") || t.includes("HOOKS")) return "hooks";
  if (t.includes("OUTLINE")) return "outline";
  if (t.includes("VIDEO CONCEPT")) return "concept";
  if (t.includes("TRANSITION")) return "transitions";
  if (t.includes("NARRATION") || t.includes("SCRIPT")) return "script";
  if (t.includes("B-ROLL") || t.includes("BROLL")) return "broll";
  if (t.includes("PRODUCTION")) return "notes";
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

// Ordered list of section keys for both long and shorts modes
export const LONG_SECTION_ORDER = [
  "angles", "concept", "hooks", "outline", "script", "transitions", "broll", "notes",
];
export const SHORTS_SECTION_ORDER = [
  "hooks", "shortScript", "onScreen", "broll", "caption", "hashtags", "titleVariants", "coverPrompts", "notes",
];


// =====================================================================
// Send-to-Studio extractors
// =====================================================================

/**
 * Pull just the spoken narration out of a script-engine output.
 * - Prefers the canonical "FULL NARRATION SCRIPT" (long) or "SHORT-FORM SCRIPT"
 *   (shorts) section; falls back to the whole text.
 * - Strips inline [B-ROLL: ...] and [ON-SCREEN: ...] directive cues.
 * - Strips standalone bracket beat headers like [HOOK — 0:00–0:30].
 * - Strips markdown bold/italic so the avatar doesn't read out the asterisks.
 * - Collapses multi-line whitespace into clean paragraphs.
 */
export function extractNarration(raw) {
  if (!raw) return "";
  const sections = parseSections(raw);
  let narration = sections.script?.body || sections.shortScript?.body || raw;

  // Drop inline directive cues (anywhere they appear)
  narration = narration.replace(/\[\s*(B-?ROLL|ON[- ]SCREEN)\s*:[^\]]*\]/gi, "");
  // Strip markdown emphasis FIRST — Claude wraps beat headers in **...** so we
  // need to remove the asterisks before the bracket-strip can match the line.
  narration = narration.replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1");
  // Drop standalone bracket beat headers on their own line (single-line bracket only)
  narration = narration.replace(/^\s*\[[^\]\n]*\]\s*$/gm, "");
  // Strip code backticks
  narration = narration.replace(/`+/g, "");
  // Collapse: trim every line, drop empties, rejoin with blank line between paragraphs
  narration = narration
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n\n");
  return narration;
}

/**
 * Pull B-roll prompts out of the consolidated "B-ROLL SHOT LIST" section.
 * - Reads bulleted lines (-, *, •).
 * - Skips section-title lines (e.g. "**Hook**", "[Section title]:") and prefixes
 *   like "Section: " or "- [Section]:".
 * - Strips bold/quote markers.
 * - Truncates lines longer than 200 chars (safety).
 * - Caps at `maxCount` (default 12 — matches Studio's MAX_SCENES).
 */
export function extractBrollPrompts(raw, maxCount = 12) {
  if (!raw) return [];
  const sections = parseSections(raw);
  const body = sections.broll?.body || "";
  if (!body) return [];
  const out = [];
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (!/^[-*•]\s+/.test(line)) continue; // only bulleted items
    let cleaned = line
      .replace(/^[-*•]\s+/, "")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/^\[(.+?)\]\s*:?\s*/, "")
      .replace(/^"+|"+$/g, "")
      .replace(/^'+|'+$/g, "")
      .trim();
    if (!cleaned) continue;
    if (cleaned.length > 200) cleaned = cleaned.slice(0, 200);
    out.push(cleaned);
    if (out.length >= maxCount) break;
  }
  return out;
}
