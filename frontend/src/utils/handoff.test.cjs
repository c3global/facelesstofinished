// Standalone regression test for the Script→Studio handoff.
// Run with:  cd /app/frontend && node src/utils/handoff.test.cjs
//
// Bug guarded against (v1.20.12): a previous fix silently REPLACED the
// script author's `brollPrompts` with LLM-generated paired prompts inside
// the Studio handoff useEffect. The corrected behaviour must preserve
// `payload.brollPrompts` EXACTLY — same order, same wording, same count —
// and MUST NOT call `/studio/broll-prompts` from within the handoff
// useEffect. If stock queries need derivation, the backend does it at
// Preview Clips + Render time (via `_extract_stock_query` /
// `_resolve_stock_query_for_scene`), never here.

const fs = require("fs");
const path = require("path");
const assert = require("assert");

const STUDIO_JSX = path.join(__dirname, "..", "pages", "Studio.jsx");
const source = fs.readFileSync(STUDIO_JSX, "utf8");

// -----------------------------------------------------------------------
// Extract the exact block of the handoff useEffect. It starts at the
// "Pick up a script handed off from /scripts via localStorage" comment
// and ends at the first `}, []);` that closes an empty dependency array.
// -----------------------------------------------------------------------
const startMarker = "Pick up a script handed off from /scripts via localStorage";
const startIdx = source.indexOf(startMarker);
assert.ok(startIdx > 0, "Could not locate the handoff useEffect comment");

// Find the `useEffect(() => {` after the comment, then walk balanced braces
// through to the matching `}, []);`.
const useEffectMarker = "useEffect(() => {";
const ueIdx = source.indexOf(useEffectMarker, startIdx);
assert.ok(ueIdx > 0, "Could not locate the handoff useEffect start");

// Walk brace depth until we hit the closing `})` followed by `, []);`.
let depth = 0;
let end = -1;
for (let i = ueIdx; i < source.length; i++) {
  const ch = source[i];
  if (ch === "{") depth += 1;
  else if (ch === "}") {
    depth -= 1;
    if (depth === 0) {
      // Confirm this is the useEffect closer (must be followed by `, []`).
      const tail = source.slice(i, i + 8);
      if (/^\}\s*,\s*\[\s*\]\s*\)/.test(tail)) {
        end = i + tail.match(/^\}\s*,\s*\[\s*\]\s*\)/)[0].length;
        break;
      }
    }
  }
}
assert.ok(end > 0, "Could not locate the handoff useEffect end");

const handoffBlock = source.slice(ueIdx, end);

console.log(`Extracted handoff useEffect block (${handoffBlock.length} chars)`);

// -----------------------------------------------------------------------
// Rule 1: the handoff useEffect MUST NOT call `/studio/broll-prompts`.
// If it did, the LLM output could silently replace the script author's
// prompts — the exact defect this test prevents from regressing.
// -----------------------------------------------------------------------
const brollApiCall = /apiClient\.post\(\s*["']\/studio\/broll-prompts["']/;
assert.strictEqual(
  brollApiCall.test(handoffBlock),
  false,
  "REGRESSION: handoff useEffect calls /studio/broll-prompts. It must not — " +
    "the script author's brollPrompts must be preserved exactly, and stock " +
    "queries derive via the backend sanitizer instead."
);

// Rule 2: the handoff useEffect MUST NOT call ANY API in general — a
// stricter form of Rule 1 catching any future regeneration attempt.
const anyApiCall = /apiClient\.(post|get|put|delete|patch)\(/;
assert.strictEqual(
  anyApiCall.test(handoffBlock),
  false,
  "REGRESSION: handoff useEffect issues an API call. The handoff must be a " +
    "pure state-set — no server round-trip that could alter prompts."
);

// Rule 3: the handoff MUST preserve `payload.brollPrompts` verbatim by
// piping them straight into `setBulkPrompts(payload.brollPrompts.join(...))`.
const preservesBroll = /setBulkPrompts\(\s*payload\.brollPrompts\.join\(/;
assert.ok(
  preservesBroll.test(handoffBlock),
  "REGRESSION: handoff useEffect no longer writes payload.brollPrompts " +
    "directly into bulkPrompts — prompts may be transformed."
);

// Rule 4: the handoff must NOT rebuild the bulk prompts from LLM `scenes`.
const rebuildsFromScenes = /\.data\.scenes/;
assert.strictEqual(
  rebuildsFromScenes.test(handoffBlock),
  false,
  "REGRESSION: handoff useEffect reads `r.data.scenes` — that indicates " +
    "the paired-output flow is being consumed to rebuild prompts."
);

// Rule 5: overrides array is aligned 1-to-1 with the raw brollPrompts.
const overridesAligned = /setSceneOverrides\(\s*payload\.brollPrompts\.map\(/;
assert.ok(
  overridesAligned.test(handoffBlock),
  "REGRESSION: setSceneOverrides is no longer sized from payload.brollPrompts, " +
    "which breaks the one-to-one prompt→override alignment."
);

console.log("✅ Handoff preserves the original brollPrompts (order, count, wording).");
console.log("✅ No /studio/broll-prompts call inside the handoff useEffect.");
console.log("✅ No apiClient calls of any kind inside the handoff useEffect.");
console.log("✅ setBulkPrompts writes payload.brollPrompts.join(...) directly.");
console.log("✅ setSceneOverrides is aligned 1-to-1 with payload.brollPrompts.");

// -----------------------------------------------------------------------
// Preview Clips regression — the fetchCandidates call must forward each
// scene's `search_query` alongside `prompts`, so the backend can route
// stock providers by the paired query first and sanitized-prompt fallback
// only when the query is missing.
// -----------------------------------------------------------------------
const previewClipsBlockStart = source.indexOf('apiClient.post("/studio/stock-candidates"');
assert.ok(
  previewClipsBlockStart > 0,
  "Could not locate the Preview Clips request in Studio.jsx"
);
const previewClipsBlock = source.slice(previewClipsBlockStart, previewClipsBlockStart + 800);

const sendsSearchQueries = /search_queries\s*:\s*stockGroups\[src\]\.map\(/;
assert.ok(
  sendsSearchQueries.test(previewClipsBlock),
  "REGRESSION: Preview Clips no longer sends `search_queries` — it will " +
    "leak detailed AI prompts to Pexels/Pixabay for scenes that already " +
    "have a paired stock query."
);

console.log("✅ Preview Clips sends `search_queries` alongside `prompts`.");
console.log("");
console.log("ALL ASSERTIONS PASSED");
