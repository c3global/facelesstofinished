// CommonJS shim of parser.js for the standalone unit test.
// Mirrors src/utils/parser.js verbatim. Keep in sync.

const KNOWN_SECTION_KEYS = new Set([
  "shortScript", "onScreen", "caption", "hashtags",
  "coverPrompts", "titleVariants", "angles", "hooks",
  "outline", "concept", "transitions", "script",
  "broll", "notes",
]);

function parseSections(raw) {
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

function extractNarration(raw) {
  if (!raw) return "";
  const sections = parseSections(raw);
  let narration = sections.script?.body || sections.shortScript?.body || raw;
  narration = narration.replace(/\[\s*(B-?ROLL|ON[- ]SCREEN)\s*:[^\]]*\]/gi, "");
  narration = narration.replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1");
  narration = narration.replace(/^\s*\[[^\]\n]*\]\s*$/gm, "");
  narration = narration.replace(/`+/g, "");
  narration = narration.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).join("\n\n");
  return narration;
}

function extractBrollPrompts(raw, maxCount = 12) {
  if (!raw) return [];
  const sections = parseSections(raw);
  const body = sections.broll?.body || "";
  if (!body) return [];
  const out = [];
  for (const rawLine of body.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (!/^[-*•]\s+/.test(line)) continue;
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

module.exports = { parseSections, extractNarration, extractBrollPrompts };
