// Parse the script-engine markdown output into named sections keyed by ### header.
// Ported from the legacy Netlify parser.

// List of known top-level section keys we expect from the script-engine output.
// Any heading whose classified key isn't in this set is treated as sub-content
// of the currently-open section (so e.g. "### Trap #1" doesn't start a new section).
const KNOWN_SECTION_KEYS = new Set([
  "shortScript", "onScreen", "caption", "hashtags",
  "coverPrompts", "titleVariants", "angles", "hooks",
  "outline", "concept", "transitions", "script",
  "broll", "notes",
]);

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
    // Accept any markdown heading level — Claude often uses '# VIDEO CONCEPT'
    // for top-level sections and '###' for sub-headings, even though the prompt
    // template says '###'. We classify the heading text and only START a new
    // section when classify() resolves to a known top-level key.
    const m = line.match(/^#{1,6}\s+(.+)$/);
    if (m) {
      const title = m[1].trim();
      const key = classify(title);
      if (KNOWN_SECTION_KEYS.has(key)) {
        flush();
        current = { key, title };
        continue;
      }
    }
    if (current) buffer.push(line);
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

// =====================================================================
// Content Sprint parser — split a single sprint output into 5 variants
// =====================================================================

/**
 * Parse a Content Sprint output string into an array of variant objects.
 * Each variant has `{ index, name, angle, category, body }`.
 * The split key is the literal header: `### 🎬 SPRINT VARIANT N — name`
 * — but we also tolerate the emoji being missing.
 */
export function parseSprintVariants(raw) {
  if (!raw) return [];
  const lines = raw.split(/\r?\n/);
  const variants = [];
  let current = null;
  let buffer = [];

  const HEADER = /^#{1,6}\s+(?:\p{Extended_Pictographic}\s*)?SPRINT\s+VARIANT\s+(\d+)\s*[—–-]?\s*(.*)$/iu;

  const flush = () => {
    if (current) {
      const body = buffer.join("\n").trim();
      const angleMatch = body.match(/\*\*Angle:\*\*\s*(.+)/i);
      const catMatch = body.match(/\*\*Category:\*\*\s*([a-z-]+)/i);
      variants.push({
        index: current.index,
        name: current.name,
        angle: angleMatch ? angleMatch[1].trim() : "",
        category: catMatch ? catMatch[1].trim().toLowerCase() : "curiosity",
        body,
      });
      buffer = [];
    }
  };

  for (const line of lines) {
    const m = line.match(HEADER);
    if (m) {
      flush();
      current = { index: parseInt(m[1], 10), name: (m[2] || "").trim() };
      continue;
    }
    if (current) buffer.push(line);
  }
  flush();
  return variants;
}
