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
