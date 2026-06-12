// Quick standalone sanity check for extractNarration / extractBrollPrompts.
// Run with:  cd /app/frontend && node src/utils/parser.test.cjs
// (No test runner needed — just asserts.)

const { extractNarration, extractBrollPrompts } = require("./parser.cjs");
const assert = require("assert");

const SAMPLE_LONG = `### 🎯 TOPIC ANGLES
1. **Menopause Metabolism Fix** — How animal-based rebalances hormones
2. **Ancestral Eating** — Reconnecting with nutrient-dense traditions

**Recommended:** Angle #1.

### 🪝 HOOK VARIATIONS
1. [Curiosity Gap] — "You're eating 'healthy' but still tired."

### 🎙️ FULL NARRATION SCRIPT

**[HOOK — 0:00–0:30]**
You're over 40. You're tired. You feel like you're doing everything right.
[B-ROLL: woman in her 40s looking tired in a bright kitchen]
And yet the scale won't budge. Here's what nobody tells you.
[B-ROLL: close-up of vegetables and salad on a plate]

**[SECTION 1: WHY YOUR CURRENT DIET MIGHT BE FAILING YOU — 1:00–2:30]**
Most diets aimed at women over 40 are protein-starved.
[B-ROLL: chicken breast being prepared on a wooden board]
That's because we were told fat is the enemy. **It isn't.**
[ON-SCREEN: Protein > calories]

**[OUTRO + CTA — 6:30–7:00]**
If this resonated, subscribe.
[B-ROLL: laptop with subscribe button on screen]

### 🎥 B-ROLL SHOT LIST
**Hook**
- woman in her 40s looking tired in a bright kitchen
- close-up of vegetables and salad on a plate

**Section 1**
- chicken breast being prepared on a wooden board
- raw eggs cracked into a bowl in slow motion

**Outro**
- laptop with subscribe button on screen

### 💡 PRODUCTION NOTES
- Cinematic tone
- Voiceover: warm, conversational`;

const narration = extractNarration(SAMPLE_LONG);
console.log("=== NARRATION ===");
console.log(narration);
console.log();

// Must NOT contain section headers
assert(!narration.includes("### "), "narration should not contain ### headers");
assert(!narration.includes("TOPIC ANGLES"), "narration should not include angles section");
assert(!narration.includes("HOOK VARIATIONS"), "narration should not include hook variations");
// Must NOT contain bracket beat markers
assert(!narration.includes("[HOOK"), "narration should drop [HOOK ...]");
assert(!narration.includes("[SECTION 1"), "narration should drop [SECTION 1 ...]");
assert(!narration.includes("[OUTRO"), "narration should drop [OUTRO ...]");
// Must NOT contain inline directive cues
assert(!narration.includes("[B-ROLL:"), "narration should drop inline [B-ROLL: ...]");
assert(!narration.includes("[ON-SCREEN:"), "narration should drop inline [ON-SCREEN: ...]");
// Must NOT contain markdown bold
assert(!narration.includes("**"), "narration should strip ** markers");
// Must contain actual spoken text
assert(narration.includes("You're over 40."), "narration should include the opening sentence");
assert(narration.includes("subscribe"), "narration should include the closing CTA word");

const prompts = extractBrollPrompts(SAMPLE_LONG);
console.log("=== B-ROLL PROMPTS ===");
prompts.forEach((p, i) => console.log(`  ${i + 1}. ${p}`));
console.log();

assert.strictEqual(prompts.length, 5, `expected 5 B-roll prompts, got ${prompts.length}`);
assert.strictEqual(prompts[0], "woman in her 40s looking tired in a bright kitchen");
assert.strictEqual(prompts[1], "close-up of vegetables and salad on a plate");
assert.strictEqual(prompts[4], "laptop with subscribe button on screen");

console.log("✅ ALL ASSERTIONS PASSED");

// =====================================================================
// Regression: Claude sometimes uses '#' (h1) for top-level sections and
// '###' (h3) for sub-headings inside a section. The parser must accept any
// heading level for known section keys, AND must treat unknown sub-headings
// as in-section content (not start a new section).
// =====================================================================

const SAMPLE_MIXED_HEADINGS = `# 🎬 VIDEO CONCEPT
**Working Title:** "Hook Strategy"
Some narrative.

# 🪝 HOOK VARIATIONS
1. Hook A
2. Hook B

# 🎙️ FULL NARRATION SCRIPT

### Trap #1: You Overestimate the Audience
Trap one narration here.

### Section 1
More content in the script.

# 🎥 B-ROLL SHOT LIST
- one
- two
`;

const sections = require("./parser.cjs").parseSections(SAMPLE_MIXED_HEADINGS);
console.log("=== MIXED-HEADING SECTIONS ===");
console.log(Object.keys(sections));
assert(sections.concept, "concept section must be present from single-hash heading");
assert(sections.hooks, "hooks section must be present from single-hash heading");
assert(sections.script, "script section must be present");
// 'Trap #1' must NOT have created a new top-level section — it should be inside script
assert(sections.script.body.includes("Trap #1"), "sub-headings should be folded into the parent script section");
assert(sections.script.body.includes("Section 1"), "Section 1 sub-heading should remain inside script");
assert(sections.broll, "broll section must be present");
assert.strictEqual(sections.broll.body.split("\n").filter((l) => l.startsWith("- ")).length, 2, "broll should have 2 bullets");

console.log("✅ MIXED-HEADING REGRESSION PASSED");
