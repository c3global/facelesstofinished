// Public-facing changelog. Surfaced in the site footer (Footer.jsx) via the
// version pill that expands inline.
//
// === RULES FOR EDITING ===
// 1. Customer-facing voice only. NO admin panels, webhooks, internal tooling,
//    migration scaffolding, or backend plumbing. Customers do not care about
//    Pinball, GoHighLevel, Netlify imports, CSV importers, or admin auto-refresh
//    polling — those go in PRD.md (internal), not here.
// 2. Plain English. "Faster renders" beats "parallelized Kokoro TTS task with
//    create_task." "Fixed an issue where long videos failed at the voiceover
//    step" beats "RuntimeError: client has been closed."
// 3. EVERY deployment must add a new entry (or extend the latest entry if the
//    deploy is small enough to fold in). Update the date and bump APP_VERSION.
//    See PRD.md → "Workflow rule: changelog must move with every deploy."
// 4. Most recent on top. Each entry has version + date + bullet list.

export const APP_VERSION = "1.8.0";

export const CHANGELOG = [
  {
    version: "1.8.0",
    date: "2026-06-29",
    changes: [
      "Resource Library is back — five production guides (Voiceover, B-Roll, Thumbnail, Production Map, Publishing Checklist) live in the new Resources tab",
      "Fixed an issue where long Faceless videos sometimes failed at the voiceover step",
      "What's New popup added to the footer (you're reading it now) — every update will land here from now on",
    ],
  },
  {
    version: "1.7.0",
    date: "2026-06-25",
    changes: [
      "Compare-all view for multi-platform shorts — see YouTube, Reels, and TikTok side-by-side in their signature colors",
      "Per-platform Send-to-Studio button under each phone in compare view — one click to pick your winner",
      "New 'New short / New script / New sprint' button in the result toolbar so you can start fresh without changing modes",
      "Recent scripts list now filters by current mode (Shorts hides Long-form, with a pill row to toggle)",
      "Phone rim color now matches the loaded script's platform — Reels = fuchsia, TikTok = teal, YouTube = red",
      "YouTube cell now renders ON-SCREEN / B-ROLL chips correctly",
      "TikTok captions are easier to read — switched to dark ink for legibility",
      "Cleaner result-page layout — Production Notes and Cover Image Prompts now align side-by-side",
      "Better color coding across script sections — B-Roll is green, On-Screen Text is cyan, Cover Image Prompts is orange",
    ],
  },
  {
    version: "1.6.0",
    date: "2026-06-19",
    changes: [
      "Faster Faceless renders — voiceover now generates in parallel with visuals (10-15 seconds saved per render)",
      "Smarter B-roll selection — stock footage now actually matches your script (was getting distracted by camera-direction keywords)",
      "Higher-quality stock footage — 720p floor, 1080p ceiling (no more soft 480p clips)",
      "Star your favorite voices — pinned to the top of every tab plus a dedicated ★ tab",
      "Star your favorite avatars — same star-toggle pattern across the full HeyGen catalog",
      "Voice picker now has a Neutral tab (76 voices that were previously hidden)",
      "Custom voice uploads now show up correctly in the picker",
      "Avatar picker no longer gets stuck loading",
      "Hook variations render cleanly without spurious blank lines",
      "Copy Script preserves formatting (green B-roll cues, amber scene headers) when pasted into Google Docs, Notion, or Word",
      "Watch your script form live — progressive rendering with phase-aware status",
      "Three new long-form toggles: include/exclude Hook Variations, B-Roll Shot List, Production Notes",
    ],
  },
  {
    version: "1.5.0",
    date: "2026-06-13",
    changes: [
      "Redesigned login page with a landing-style hero introducing what Faceless to Finished is",
      "Returning vs. first-time login experience — copy adapts automatically",
      "New 4-device hero mockup with a subtle purple/amber glow",
      "Light mode hero gradient now reads cleanly on near-white backgrounds",
      "Welcome toast on first sign-in after purchase",
      "Result page redesigned as a bento grid — phone hero at the top, eight result cards below in a responsive 3-column layout",
    ],
  },
  {
    version: "1.4.0",
    date: "2026-06-11",
    changes: [
      "Two-step script generation — first see 4 distinct creative angles (Curiosity, Contrarian, How-To, Story, List), then commit to the one you want",
      "Sprint mode — generate 5 variants of the same short in one click for A/B testing",
      "Saved angles — bookmark any angle and recall it later",
      "'Cut into a Short' — repurpose any long-form script as a Shorts script in one click",
      "'Send to Studio' handoff — one click from script to video render with B-roll prompts pre-filled",
      "Multi-platform Shorts — generate YouTube + Reels + TikTok variants together, each tuned for that platform",
    ],
  },
  {
    version: "1.3.0",
    date: "2026-05-29",
    changes: [
      "Studio launched — Avatar mode (HeyGen avatar talking head + voiceover) and Faceless mode (AI voiceover + B-roll slideshow)",
      "Six picker modals: Avatar, Voice (HeyGen), TTS Voice, B-Roll Source, Aspect, Captions — each with tabs, search, and scrolling",
      "Captions auto-flip — ON for 9:16, OFF for 16:9 — with a sticky override",
      "Auto scene generation from script paragraphs (up to 12 scenes)",
      "Per-scene B-roll source override (AI / Pexels / Pixabay) with a 'Mix per scene' option",
      "Three thumbnail previews per scene — see candidates and pick your favorite before render",
      "Bring your own B-roll — upload screen recordings, images, or screenshots and we'll animate them in",
      "Record your own voiceover in the browser if you don't want AI TTS",
      "Caption burn-in with Top / Bottom / Center placement",
      "Inline video player — watch finished renders inside the app without opening a new tab",
      "Run multiple renders at once with live per-scene status (\"Stitching scene 4 of 5…\")",
    ],
  },
  {
    version: "1.2.0",
    date: "2026-05-26",
    changes: [
      "Script Engine launched — Long-form (with Short / Medium / Long length presets) and Shorts (with YouTube / Reels / TikTok platform presets)",
      "Optional angle bias input to nudge the script in a specific creative direction",
      "Section cards for the generated output — copy any section individually or the whole thing at once",
      "History sidebar with open/delete for every script you've generated",
    ],
  },
  {
    version: "1.1.0",
    date: "2026-05-23",
    changes: [
      "Dark / light theme toggle in the header, persisted across sessions",
      "Brand restyle to the deep-navy + rose-gold + red palette",
      "Avatar mode painted in warm copper, Faceless mode in purple, so you always know which pipeline you're in",
    ],
  },
  {
    version: "1.0.0",
    date: "2026-05-21",
    changes: [
      "Faceless to Finished is live on the new platform — passwordless email sign-in, JWT session, and entitlement-gated access",
      "Initial Script Engine and Studio scaffolding in place — first deploy",
    ],
  },
];
