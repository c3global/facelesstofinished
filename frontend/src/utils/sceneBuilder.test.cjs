// Standalone source-contract checks for the provider-free Scene Builder shell.
// Run with: node src/utils/sceneBuilder.test.cjs

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const pagePath = path.join(__dirname, "..", "pages", "SceneBuilder.jsx");
const appPath = path.join(__dirname, "..", "App.js");
const studioPath = path.join(__dirname, "..", "pages", "Studio.jsx");
const page = fs.readFileSync(pagePath, "utf8");
const app = fs.readFileSync(appPath, "utf8");
const studio = fs.readFileSync(studioPath, "utf8");
const scriptsPath = path.join(__dirname, "..", "pages", "Scripts.jsx");
const scripts = fs.readFileSync(scriptsPath, "utf8");

assert.ok(app.includes('path="/studio/scene-builder"'), "Scene Builder dashboard route is missing");
assert.ok(app.includes('path="/studio/scene-builder/:projectId"'), "Scene Builder editor route is missing");
assert.ok(studio.includes('to="/studio/scene-builder"'), "Quick Render does not link to Scene Builder");
assert.ok(
  scripts.includes('data-testid="scripts-send-to-scene-builder"'),
  "Script Engine handoff button is missing",
);
assert.ok(
  scripts.includes('hasStudioEntitlement && output.mode !== "sprint"'),
  "Script Engine handoff is not hidden from non-Studio users",
);
assert.ok(
  scripts.includes('apiClient.post("/studio/projects"'),
  "Script Engine handoff does not create a real saved project",
);
assert.ok(
  scripts.includes("broll_prompts: brollPrompts"),
  "Script Engine handoff does not preserve the original B-roll prompts",
);

assert.ok(page.includes("scene.narration.text"), "Editor no longer displays exact narration text");
assert.ok(page.includes("scene.narration.word_start + 1"), "Editor no longer displays narration word ranges");
assert.ok(page.includes("detailed_prompt"), "Detailed visual direction control is missing");
assert.ok(page.includes("stock_query"), "Stock-search query control is missing");
assert.ok(page.includes("expected_revision: revision.version"), "Autosave lost optimistic revision locking");

const forbiddenRequests = [
  "/studio/render",
  "/studio/stock-search",
  "/studio/stock-candidates",
  "/studio/ai-previews",
  "/studio/broll-prompts",
  "/render/estimate",
];
for (const endpoint of forbiddenRequests) {
  assert.strictEqual(
    page.includes(endpoint),
    false,
    `Scene Builder preview must not call ${endpoint}`,
  );
}

assert.ok(
  page.includes("Stock results are intentionally disabled in this preview"),
  "Stock provider boundary is not explained in the preview",
);
assert.ok(
  page.includes("No image will be generated in this preview"),
  "AI provider boundary is not explained in the preview",
);

console.log("✅ Scene Builder dashboard and editor routes are registered.");
console.log("✅ Exact narration ranges and separate prompt fields remain visible.");
console.log("✅ Autosave uses optimistic revision locking.");
console.log("✅ Script Engine handoff is Studio-only and preserves B-roll prompts.");
console.log("✅ No render, stock-search, AI-preview, or prompt-generation calls exist in the shell.");
console.log("ALL ASSERTIONS PASSED");
