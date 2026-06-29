// Public-facing changelog. Surfaced in the site footer (Footer.jsx) via the
// version pill that expands inline — same pattern as the legacy Netlify build
// (/app/legacy_netlify/src/changelog.js, but rewritten for the Emergent app
// with the full migration history backfilled).
//
// Edit this file every time a customer-visible change ships. The
// in-app footer popup reads from CHANGELOG; APP_VERSION is also displayed
// next to the © copyright line.

export const APP_VERSION = "1.8.0";

export const CHANGELOG = [
  {
    version: "1.8.0",
    date: "2026-06-29",
    changes: [
      "Resource Library restored — the 5 production guides (Voiceover, B-Roll, Thumbnail, Production Map, Publishing Checklist) are now back in the header nav after the platform migration",
      "Faceless renders no longer fail with the 'client has been closed' error on long scripts",
      "Public changelog reintroduced in the footer (you're reading it now)",
    ],
  },
  {
    version: "1.7.5",
    date: "2026-02-23",
    changes: [
      "Multi-platform compare-all view — see YouTube + Reels + TikTok side-by-side in their signature colors",
      "Per-platform Send-to-Studio buttons under each phone in compare view",
      "Persistent 'New short' / 'New script' button in the result-page toolbar so you can start fresh without flipping modes",
      "Recent-scripts list filters by current mode (Shorts hides Long, with a pill row to toggle)",
      "Phone rim now matches the loaded script's platform (Reels = fuchsia, TikTok = teal, YouTube = red)",
      "YouTube cell in compare-all now renders ON-SCREEN / B-ROLL chips correctly (was showing as raw bracketed text)",
      "TikTok TEXT chips switched to dark ink — finally legible on the bright-teal background",
      "Production Notes + Cover Image Prompts now align side-by-side at equal width",
      "Section card colors rebalanced — B-Roll is green, On-Screen Text is cyan, Cover Image Prompts is bright orange",
    ],
  },
  {
    version: "1.7.0",
    date: "2026-02-19",
    changes: [
      "Faster Faceless renders — voiceover now runs in parallel with image generation (10-15s saved per render)",
      "Smarter B-roll selection — stock searches strip cinematic vocabulary so stock footage actually matches your script",
      "Stock footage resolution floor bumped to 720p, ceiling 1080p (no more soft 480p clips)",
      "Favorite voices and avatars — star toggle + ★ tab in both pickers",
      "Voice picker now has a 'Neutral' tab (recovers 76 voices previously hidden)",
      "Avatar picker no longer stuck loading — backend timeout bumped 30s → 90s",
      "Hook variations render cleanly without spurious blank lines",
      "Copy Script preserves formatting (green B-roll cues, amber scene headers) when pasted into Google Docs / Notion / Word",
      "Drip / progressive script rendering — see Claude's output stream live with phase-aware status labels",
      "Long-form toggles for Hook Variations, B-Roll Shot List, Production Notes (default ON)",
      "Login page redesigned with landing-style hero and conditional first-time-vs-returning copy",
      "Admin-granted buyers can now sign in (critical bug fix)",
      "Pinball webhook now accepts every real-world payload shape (was too strict before)",
      "One-shot welcome toast on first sign-in after purchase",
      "Shorts result page redesigned with a bento grid (phone hero + 8 auxiliary cards in a 3-col grid)",
    ],
  },
  {
    version: "1.6.0",
    date: "2026-02-18",
    changes: [
      "Native Admin Panel — Buyers, Activity, Stats tabs all inside the app",
      "Pinball webhook receiver — auto-provisions buyers on every paid order",
      "Netlify Buyer Import — bulk-migrate legacy customers with smart merge",
      "CSV Import for Buyers (drop a file, batch-create records)",
      "Activity log management — multi-select delete, bulk delete, wipe-all with confirm",
      "Auto-refresh on Buyers + Activity tabs (20s polling — new webhook events surface in seconds)",
    ],
  },
  {
    version: "1.5.0",
    date: "2026-01-12",
    changes: [
      "Studio launched — Avatar (HeyGen) and Faceless (AI voiceover + B-roll) pipelines",
      "Script Engine 2.0 — two-step flow with 4 distinct angles to pick from before commit",
      "Sprint mode — 5 variants of the same short in one click for A/B testing",
      "Saved angles — bookmark and recall any creative angle",
      "'Cut into a Short' — repurpose any long-form script as a Shorts script",
      "'Send to Studio' handoff — one click from script to video render",
      "Multi-platform Shorts — generate YouTube + Reels + TikTok variants together",
      "6 picker modals: Avatar, Voice (HeyGen), TTS Voice (Kokoro), B-Roll Source, Aspect, Captions",
      "Captions auto-flip (ON for 9:16, OFF for 16:9) with sticky override",
      "Auto scene generation from script paragraphs (up to 12 scenes)",
      "Per-scene B-roll source override (AI / Pexels / Pixabay)",
      "3-thumbnail B-roll preview per scene before render",
      "User-uploaded B-roll (screen recordings, images, screenshots)",
      "User-recorded voiceover (record in browser, skip AI TTS)",
      "Caption burn-in with Top / Bottom / Center placement",
      "Inline video player (no more blank CDN tabs)",
      "Concurrent renders with live per-scene status",
    ],
  },
];
