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

export const APP_VERSION = "1.18.3";

export const CHANGELOG = [
  {
    version: "1.18.3",
    date: "2026-06-30",
    changes: [
      "Fixed: Avatar renders with long scripts were failing at 45% with a wall of raw HeyGen error JSON. HeyGen's API caps script text at 5,000 characters (about 750 words) — we now catch this BEFORE submitting so you see a clean, friendly hint instead",
      "The hint now points you to Faceless mode when Avatar is too short for your content — Faceless has no character limit because its voiceover is chunked scene-by-scene",
      "Both single-aspect and both-aspects renders share the same guard, so long scripts can't break either path",
    ],
  },
  {
    version: "1.18.2",
    date: "2026-06-30",
    changes: [
      "Public nav (Roadmap · Changelog · Sign in) now lives in the main header on the same row as the logo and theme toggle — no more separate row of links below the hero",
      "Footer now renders on the login page too, so the version pill and 'What's New' dot are visible from your very first visit",
      "Refreshed the roadmap copy — it now reads for every customer (Founders, lifetime-deal holders, and everyone who joins us later), not just one launch partner",
      "Renamed Shipped 'Redemption flow' → 'Redemption codes' and In Progress 'Production launch' so the language stays audience-neutral",
    ],
  },
  {
    version: "1.18.1",
    date: "2026-06-30",
    changes: [
      "Fixed: thumbnail prompt copy-over was truncating to the `[matches \"...\"]` label (~57 chars) instead of the full 500-700 char prompt body. Now the entire cover concept lands in the textarea when you click a chip",
      "Roadmap is now editable — admins can add, edit, reorder, and delete items inline directly on /roadmap. Buyers see the polished read-only version",
      "Added Script Revision Tools (TOP REQUEST), Brand Voice Profiles, Authority Content Templates, Content Series Builder to Planned",
      "Added Approval Workflow, Multilingual Scripts, and Agency / White-label to Considering",
      "Added the positioning subhead: \"the AI studio for off-camera authority content — built for consultants, coaches, experts, and speakers\"",
      "Landing page now has a top-right nav (Roadmap · Changelog · Sign in) so reviewers can browse before signing up",
      "New public /changelog page with a timeline view of every shipped version",
      "Scripts page shows a one-shot release banner pointing to the roadmap — dismisses per version",
    ],
  },
  {
    version: "1.18.0",
    date: "2026-06-30",
    changes: [
      "New public Roadmap page — see what we've shipped, what we're building now, and what's coming next. Linked from the footer (no login required)",
      "Shipped column highlights Script Engine, Studio Avatar + Faceless, Thumbnail Engine, BYOK vault, and redemption codes",
      "Tell us which Considering item matters most — top requests get fast-tracked into Planned",
    ],
  },
  {
    version: "1.17.0",
    date: "2026-06-30",
    changes: [
      "Light mode polish round 2 — the 'FACELESS TO FINISHED · VIDEO ENGINE' eyebrow and the 'Owner · unlimited renders' pill are now properly legible on the pale background. Studio and Thumbnails pages both fixed",
      "Settings/Keys page (BYOK) — all 6 service cards now render clean white in light mode with crisp dark text. No more dark-gray boxes on lavender",
      "Dark mode remains untouched — beautiful as ever",
    ],
  },
  {
    version: "1.16.0",
    date: "2026-06-30",
    changes: [
      "Light mode polish — Thumbnails page is no longer a sea of dark-gray boxes in light mode. The form card, prompt textarea, Engine/Aspect chips, and every gallery tile now use clean white surfaces with proper purple-gray text, copper-accented active states, and subtle shadows",
      "Dark mode is unchanged — same gorgeous palette",
    ],
  },
  {
    version: "1.15.0",
    date: "2026-06-30",
    changes: [
      "Cross-origin auth fixed — the deployed app now correctly authenticates regardless of which subdomain the frontend is served from (CORS spec fix, the previous wildcard-with-credentials combination was silently broken)",
      "Behind the scenes: server.py is leaner — the caption burn-in pipeline moved to its own module with its own regression test suite; Scripts page extracts script-engine constants and the platform-accent side effect into clean reusable modules",
      "No user-facing behaviour change — just faster builds, tighter codebase, fewer bugs going forward",
    ],
  },
  {
    version: "1.14.0",
    date: "2026-06-30",
    changes: [
      "Fixed Cloudflare 502 error message — when our render server briefly restarts during a deploy you'll now see 'warming back up, give it ~30 seconds' instead of a scary origin-server error",
      "Studio renders now have a 5-regenerate soft-cap per script so a tweak session can't accidentally burn through your quota — fresh inputs render better than another retry anyway. Owners and Founders are exempt",
      "Light mode polish — footer 'Have a redemption code?' link is finally legible, pill hover states actually change on hover, TikTok platform card uses dark ink so 'TikTok' is readable on the bright cyan fill",
      "Caption burn-in pipeline now covered by a regression test suite (7 tests) — future refactors can't silently disable subtitle burn-in",
    ],
  },
  {
    version: "1.13.0",
    date: "2026-06-30",
    changes: [
      "GoHighLevel integration — every new customer (purchase webhook) and every code redemption now pushes a tagged contact to your GHL workspace automatically, with tier + source + founder tags",
      "Admin Buyers tab: GHL connection pill (green when wired, amber when off), Test GHL button to verify the webhook live, per-buyer Push to GHL replay button for legacy buyers / outage recovery",
      "Failures land in the activity log as ghl_push_failed so nothing slips silently",
    ],
  },
  {
    version: "1.12.0",
    date: "2026-06-30",
    changes: [
      "New API Keys settings page (Pro Plus + Founder) — plug in your own Anthropic, OpenAI, Google AI Studio, ElevenLabs, HeyGen, and fal.ai keys and your renders draw from your own provider quotas instead of ours",
      "Anthropic key unlocks the Script Engine + thumbnail prompt rewriter on your own Claude quota",
      "Keys are encrypted at rest and never displayed once saved — only a safe preview like 'sk-…0abc'",
      "Find it in your Profile menu → API keys",
      "Thumbnails — click any thumbnail in your gallery to open a full-screen preview, with Download + Copy prompt actions right there",
      "Admin Usage tab — thumbnails now show up alongside scripts & renders, with Premium/Fast split in the drilldown + a new Thumbnails sort column and total tile in Stats",
    ],
  },
  {
    version: "1.11.0",
    date: "2026-06-30",
    changes: [
      "Profile dropdown menu in the header — quick access to your tier, redeem codes, and sign out from one place",
      "New code redemption flow — paste any access code on the Redeem page (linked from the footer, the login screen, and your Profile menu) and we'll unlock your plan instantly",
      "Tier names refreshed — Starter / Creator / Pro / Pro Plus (Founder badge unchanged for our OG legacy members)",
      "Founders now get a subtle copper accent throughout the app + a 'Founder' badge in the header",
      "Upgrade button appears in the quota popover when you're running low — links to the right place automatically",
    ],
  },
  {
    version: "1.10.2",
    date: "2026-06-30",
    changes: [
      "Fixed: 'Make thumbnail' now correctly extracts your 3 cover concepts from long-form scripts (was silently falling back to the truncated narration because of a markdown bold-wrapping quirk in the parser)",
      "Cover concepts picker now shows all 3 options with their matching title variants — pick the one you want, or hit Generate all 3 to compare",
    ],
  },
  {
    version: "1.10.1",
    date: "2026-06-30",
    changes: [
      "Long-form scripts now get 3 Title/Thumbnail variants + 3 ready-to-go Cover Image Prompts (matches what Shorts has had all along)",
      "Click 'Make thumbnail' on any new script and you'll see a picker of 3 cover concepts — choose the one you like, or hit 'Generate all 3' to compare them side-by-side",
      "Dramatically upgraded the thumbnail rewriter — every prompt now bakes in viral YouTube thumbnail rules: expressive focal subject, bold color palette, dramatic cinematic lighting, clear space for overlay text",
      "Final image prompts get a hidden viral-style boost suffix before they hit OpenAI — more 'top creator' production quality, less stock-photo flat",
      "Confirmation prompt when you hit 'Generate all 3' on a quota-bound tier — never burn 3 slots by accident",
    ],
  },
  {
    version: "1.10.0",
    date: "2026-06-30",
    changes: [
      "NEW: Thumbnail Engine — generate click-worthy YouTube and Shorts thumbnails right inside Faceless 48. Pick Premium for hero shots or Fast for quick A/B testing",
      "Built-in prompt rewriter — type a casual idea and tap 'Rewrite for me' to get a vivid, image-ready prompt",
      "Three aspect ratios baked in: 16:9 for YouTube, 9:16 for Shorts/Reels/TikTok, 1:1 for Instagram feed",
      "'Make thumbnail' button in the Script Engine result view sends your script topic + opening hook straight into the new tool",
      "Find Thumbnails as a top-level tab in the header alongside Script Engine and Studio",
    ],
  },
  {
    version: "1.9.0",
    date: "2026-06-30",
    changes: [
      "New render-budget pill in the Studio header — see how many renders you've used this cycle and when your next batch unlocks at a glance",
      "Click the pill for the full breakdown: total renders, Avatar sub-cap (Studio Pro+), and your exact cycle reset date",
      "Friendlier message when you've used your last render — no more cryptic 402s",
    ],
  },
  {
    version: "1.8.1",
    date: "2026-06-29",
    changes: [
      "What's New popup now nudges you with a subtle amber dot when there's a release you haven't seen yet — opens the popup once to dismiss",
      "Last-seen timestamps now update accurately on every sign-in (was only tracking imports and webhook events before)",
    ],
  },
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
