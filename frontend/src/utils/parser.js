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

// Safety net: occasionally Claude emits ordered-list items with a blank line
// between the number marker and its bracketed style label, which markdown
// renders as a number alone on one row and the content on the next. Collapse
// those back into a single line so the hook list reads cleanly.
// Match: `1.` (or `1.<space>`), then 1+ blank lines, then `**[Style]**` or `[Style]`.
function normalizeHookList(text) {
  return text.replace(
    /^(\d{1,2})\.\s*\n\s*\n+(\s*\*?\*?\[)/gm,
    (_, n, rest) => `${n}. ${rest}`,
  );
}

export function parseSections(raw) {
  if (!raw) return {};
  const cleaned = normalizeHookList(raw);
  const lines = cleaned.split("\n");
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
  "titleVariants", "coverPrompts",
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

/**
 * Pull cover image prompts out of the "COVER IMAGE PROMPTS" section. Returns
 * an array of {index, label, prompt} entries (max 3). Tolerates many format
 * variations Claude emits in the wild — most notably the markdown-bold
 * wrapping of the number prefix (`**1. [Curiosity variant]** — ...`) which
 * earlier versions of this regex silently failed to match.
 *
 * Format examples now handled:
 *   "1. [Curiosity] — Vivid prompt here"
 *   "1) [Bold Claim] — Vivid prompt..."
 *   "**1. [Curiosity variant]** — Vivid prompt..."  ← the one that broke us
 *   "**1.** [Question] — Vivid prompt..."
 *   "1. **[Label]** — Vivid prompt..."
 *
 * Pairs with extractTitleVariants() — both sections live next to each other
 * in the bento grid and are emitted by the same Claude pass.
 */
export function extractCoverPrompts(raw, maxCount = 3) {
  if (!raw) return [];
  const sections = parseSections(raw);
  const body = sections.coverPrompts?.body || "";
  if (!body) return [];

  // Strategy: split the body into "entries" first (each starts with a
  // numbered header like `1.` or `**1.**`), then for each entry capture
  // the header line separately from the body paragraph(s) that follow.
  //
  // Why this rewrite (bug fix v1.18.1):
  //   The earlier single-line regex `^N. [label] ... — prompt$` assumed the
  //   prompt body lived on the SAME line as the number. But Claude's current
  //   template emits the label on line 1 (`1. [matches "..."]`) and the
  //   500-700 char prompt on lines 2-6. The old regex would backtrack out of
  //   the bracket-label capture and grab the bracketed label itself as the
  //   "prompt" — putting `[matches "..."]` (~57 chars) into the textarea
  //   instead of the full prompt body. Live-demo killer.
  //
  // Formats now handled (numbered header on its own line OR with prompt
  // trailing on same line):
  //   "1. [matches \"Title\"]\nVivid prompt paragraph(s)..."
  //   "**1.** [Curiosity] — Vivid prompt..."   (single-line legacy)
  //   "1) Vivid prompt..."                     (no label at all)
  const headerRe = /^\s*(?:\*\*)?\s*(\d{1,2})\s*[.)]\s*(?:\*\*)?\s*(?:\[\s*([^\]]+?)\s*\])?\s*[—–\-:]?\s*(.*)$/;
  const lines = body.split(/\r?\n/);
  const entries = [];
  let cur = null;

  const finalize = (e) => {
    if (!e) return;
    // Concatenate: same-line tail (if any) + the paragraph body that
    // followed on subsequent lines. Strip Midjourney flags from the joined
    // text since aspect ratio is chosen via the UI picker.
    let prompt = [e.tail, e.bodyLines.join(" ").trim()]
      .filter(Boolean)
      .join(" ")
      .replace(/--ar\s+\d+:\d+/gi, "")
      .replace(/--no\s+[a-z]+(\s+[a-z]+)*/gi, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!prompt) return;
    entries.push({ index: e.index, label: e.label, prompt });
  };

  for (const rawLine of lines) {
    const cleaned = rawLine.replace(/\*\*/g, "").trim();
    if (!cleaned) {
      // Blank line — paragraph break inside the current entry. Keep going;
      // we'll re-join all paragraph lines into one prompt string at finalize.
      continue;
    }
    const m = cleaned.match(headerRe);
    // Accept as a header ONLY if (a) it actually matches AND (b) the next
    // entry index makes sense (i.e. we don't false-positive on a sentence
    // that happens to start with a digit). Header index must be 1–9.
    const looksLikeHeader =
      m && parseInt(m[1], 10) >= 1 && parseInt(m[1], 10) <= 9;
    if (looksLikeHeader) {
      finalize(cur);
      cur = {
        index: parseInt(m[1], 10),
        label: (m[2] || "").trim(),
        tail: (m[3] || "").trim(),
        bodyLines: [],
      };
      if (entries.length + (cur ? 1 : 0) > maxCount) {
        // Stop collecting after we have enough headers in flight.
        // The current `cur` will finalize at end of loop.
      }
    } else if (cur) {
      cur.bodyLines.push(cleaned);
    }
  }
  finalize(cur);
  return entries.slice(0, maxCount);
}

/**
 * Pull the 3 title/thumbnail variants out of the "TITLE / THUMBNAIL VARIANTS"
 * section. Returns array of {index, label, title} entries. Used to show
 * the title alongside its matching cover prompt in the picker UI. Same
 * markdown-strip-then-regex approach as extractCoverPrompts.
 */
export function extractTitleVariants(raw, maxCount = 3) {
  if (!raw) return [];
  const sections = parseSections(raw);
  const body = sections.titleVariants?.body || "";
  if (!body) return [];
  const out = [];
  const re = /^\s*(\d{1,2})\s*[.)]\s*(?:\[\s*([^\]]+?)\s*\])?\s*[—–\-:]?\s*(.+)$/;
  for (const rawLine of body.split(/\r?\n/)) {
    const cleaned = rawLine.replace(/\*\*/g, "").trim();
    if (!cleaned) continue;
    const m = cleaned.match(re);
    if (!m) continue;
    out.push({
      index: parseInt(m[1], 10),
      label: (m[2] || "").trim(),
      title: m[3].trim(),
    });
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

  // Strict header: `### 🎬 SPRINT VARIANT N — name`
  const HEADER = /^#{1,6}\s+(?:\p{Extended_Pictographic}\s*)?SPRINT\s+VARIANT\s+(\d+)\s*[—–-]?\s*(.*)$/iu;
  // Relaxed fallback for prompt drift (different bullet style, no em-dash, etc.)
  const HEADER_LOOSE = /^#{1,6}\s*.*?SPRINT\s+VARIANT\s+(\d+)\s*[—–\-:]?\s*(.*)$/iu;

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
    const m = line.match(HEADER) || line.match(HEADER_LOOSE);
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
