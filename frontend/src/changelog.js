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

export const APP_VERSION = "1.20.13";

export const CHANGELOG = [
  {
    version: "1.20.13",
    date: "2026-08-15",
    changes: [
      "🔒 Removed internal pricing details from the Studio experience.",
    ],
  },
  {
    version: "1.20.12",
    date: "2026-08-15",
    changes: [
      "🎯 Improved B-roll matching so stock footage searches use concise visual keywords while preserving detailed scene directions.",
    ],
  },
  {
    version: "1.20.11",
    date: "2026-08-15",
    changes: [
      "🛡️ Multiple renders now wait safely instead of competing for memory, so one customer’s active render cannot cause another queued render to disappear.",
      "🎞️ Stock-video processing now uses a production-safe memory limit and a hard search deadline, preventing the remaining 55% stall on smaller servers.",
      "💓 Waiting renders stay alive with their own heartbeat and begin automatically when processing capacity becomes available.",
    ],
  },
  {
    version: "1.20.10",
    date: "2026-08-14",
    changes: [
      "🐛 Fixed the remaining 55-69% render stall — the watchdog now recognizes the scene-processing stage and automatically closes genuinely abandoned renders instead of leaving them in progress forever.",
      "🛡️ Timed-out video processes are now fully stopped and cleaned up before another scene starts, preventing hidden memory buildup during larger renders.",
      "💓 Slow AI scenes can keep working safely — an independent worker heartbeat distinguishes a provider that is still processing from a render worker that disappeared.",
    ],
  },
  {
    version: "1.20.9",
    date: "2026-08-11",
    changes: [
      "🎬 Long-form videos now feel professional — scene count scales with script length so a 25-minute video gets 60-90 scenes (instead of 12) and an average scene is ~15 seconds instead of 2 minutes of looping stock footage.",
      "✂️ Auto-cutaways — any scene where the voiceover runs longer than 5 seconds automatically gets 2-4 different B-roll clips (same topic, different footage) so nothing loops or drags.",
      "📏 New Extended length option (25-35 minute videos, ~4,000-5,500 words) — for deeper educational, documentary, or storytelling formats.",
      "👁️ Pre-render preview banner — after 'Generate from script' you'll see the scene count, estimated video duration, and total clip count (with cutaways) so you know what you're rendering before you commit.",
    ],
  },
  {
    version: "1.20.8",
    date: "2026-08-11",
    changes: [
      "🚚 Faster, more reliable video downloads — finished videos now publish to Cloudflare's global network instead of the old storage host. Faster playback, more reliable download links, and no more broken links when the old host has a bad moment.",
    ],
  },
  {
    version: "1.20.7",
    date: "2026-08-10",
    changes: [
      "🐛 Fixed 'Local ffmpeg compose failed and remote fallback not available' — the local compose step now has a two-tier retry: fast stream-copy first (sub-second), then a bulletproof re-encode if any Pexels clip has an incompatible bitstream header. If BOTH local paths fail, we automatically promote the local clips up to fal storage and run fal-compose as an ultimate backup, so paying customers still get their video",
      "🔍 Better error surfacing — when compose fails, the render row now shows exactly which path failed (copy-concat, re-encode, or fal-compose) with the ffmpeg stderr tail so the exact cause is visible instead of a generic 'failed'",
    ],
  },
  {
    version: "1.20.6",
    date: "2026-08-10",
    changes: [
      "🚀 Rebuilt the video composition step to run locally — no more waiting on fal.ai to stitch clips together. The pipeline now concatenates everything on our server with ffmpeg (using stream-copy, so it takes about 2 seconds), then uploads just the final video once. Result: renders finish 20-30 seconds faster, cost half as much, and never hang because of fal.ai storage",
      "🛡️ Automatic fallback — if fal.ai storage is completely unreachable when the render finishes, we serve the final MP4 directly from our backend so paying customers still get their video",
      "🧹 Every render gets a job-scoped scratch directory that's auto-cleaned when the render finishes (success, failure, or cancel), so container disk stays tidy",
    ],
  },
  {
    version: "1.20.5",
    date: "2026-08-10",
    changes: [
      "✨ Tier pivot — the AppSumo t1 / t2 / t3 naming is retired. You'll see the new lineup everywhere: Starter (Script + Thumbnail), Legacy (Script + Thumbnail + Shorts — grandfathered), Founder (everything, lifetime — your original Studio buyers), and Premium (everything + Community access, $127/mo)",
      "✨ Bring Your Own Key is now available for ALL tiers — Starter, Legacy, Founder, Premium. Plug in your own OpenRouter, HeyGen, ElevenLabs, or Anthropic keys to bypass platform quotas at any level",
      "⚡ Cut the Claude retry budget from 75s → 20s so you (and your German customers) see a clean 'try again in 30s' prompt fast instead of watching the spinner for over a minute",
      "✨ Made the post-render Timeline button obvious — it now shows as a proper labelled 'Timeline' button on every completed Faceless render row instead of a tiny clock icon lost in the row",
    ],
  },
  {
    version: "1.20.4",
    date: "2026-08-10",
    changes: [
      "🐛 Fixed the 'stuck at 55% forever' bug for real this time — the cause was memory pressure from firing every scene through ffmpeg at once. Now capped at 3 scenes in parallel with a lighter ffmpeg preset, so renders fit comfortably in memory on any hosting tier",
      "🐛 Added a background watchdog that auto-recovers any render silent for more than 5 minutes — no more zombie renders left over after a redeploy",
      "✨ New Cancel button on in-progress renders — one click aborts the render and refunds the credits automatically",
    ],
  },
  {
    version: "1.20.3",
    date: "2026-08-10",
    changes: [
      "🐛 Faceless renders now show real per-scene progress during the 'Adding motion to scenes' phase (previously stuck at a static 55% for the whole phase). You'll see 'Scene 3 of 8 done…' as each one completes, so you know it's alive",
    ],
  },
  {
    version: "1.20.2",
    date: "2026-08-10",
    changes: [
      "🐛 Fixed the Faceless render getting stuck at 55% — added per-scene timeouts so one hung upload can no longer freeze the whole render. If a scene really can't process, we drop it and finish the rest instead of hanging forever",
      "🐛 Fixed the 'origin overloaded' error on Show me 5 angles — the AI retry budget was creeping past the edge network's timeout on slow days, now capped so you always get a clean response inside 75 seconds",
    ],
  },
  {
    version: "1.20.1",
    date: "2026-08-03",
    changes: [
      "New 'Freeze looping B-roll' toggle above the Faceless render button — flip it once and every future render will hold the last frame instead of looping short stock clips. No more Timeline editor round-trip for every video",
    ],
  },
  {
    version: "1.20.0",
    date: "2026-08-03",
    changes: [
      "🆕 Scene timeline editor (MVP) — open any completed Faceless render from your history and flip the new ⏱ button to control looping. Toggle 'Freeze last frame' on any scene where the stock B-roll runs shorter than the voiceover, or hit 'Freeze all scenes' to fix them in one tap. Re-render kicks a fresh Faceless job with your fixes applied. No more Groundhog Day B-roll",
    ],
  },
  {
    version: "1.19.8",
    date: "2026-07-02",
    changes: [
      "Script Engine now auto-retries when Anthropic (the AI behind your scripts) has a busy moment — up to 3 attempts with backoff, instead of surfacing a 'server overloaded' error on the first hiccup. Should cure the intermittent 520 errors on Show me 5 angles",
    ],
  },
  {
    version: "1.19.7",
    date: "2026-07-02",
    changes: [
      "Faceless 9:16 captions are now sized right — no more oversized text taking over the whole vertical frame",
      "Smarter stock B-roll matching — the script planner now generates a dedicated Pexels/Pixabay search query per scene (not the cinematic AI-video prompt), so your clips actually match what you're saying",
    ],
  },
  {
    version: "1.19.6",
    date: "2026-07-02",
    changes: [
      "You can now vote on the public roadmap — every Planned and Considering item has a thumbs-up. The loudest signals move up. First-time visitors, existing buyers, AppSumo reviewers — everybody's vote counts",
      "New Planned item: Scene timeline editor — drag-and-drop alignment so your B-roll clips line up exactly with your voiceover instead of looping past a sentence",
    ],
  },
  {
    version: "1.19.5",
    date: "2026-07-02",
    changes: [
      "Two new items joined the public roadmap under Planned — Canva B-Roll import (drop your Canva designs straight into Faceless scenes) and a Higher-quality AI video engine for cinematic motion. Head to the Roadmap page to follow along",
    ],
  },
  {
    version: "1.19.4",
    date: "2026-07-02",
    changes: [
      "Cleaner B-Roll picker — when AI generation is turned off, the AI card and AI engine chip are hidden entirely instead of showing greyed-out with disclaimers. Just the options you can actually use",
    ],
  },
  {
    version: "1.19.3",
    date: "2026-07-02",
    changes: [
      "Admins can now sign in with just their email — no email link round-trip required. Everyone else still gets our secure one-time link so accounts stay locked down",
    ],
  },
  {
    version: "1.19.2",
    date: "2026-07-02",
    changes: [
      "Cleaner Faceless Studio — build your video with beautiful stock footage from Pexels and Pixabay, or your own uploaded clips. Faster to pick, sharper on screen, and no more scrolling past options you don't need",
      "AI-generated scenes are now a Pro Plus perk. Founders and Pro Plus members keep full access; everyone else gets a simpler, distraction-free video builder",
      "Behind the scenes: we tightened our video quality standards so every Faceless render feels more on-brand for your audience",
    ],
  },
  {
    version: "1.19.1",
    date: "2026-07-02",
    changes: [
      "Faceless Studio now leads with real stock footage instead of AI scenes by default — you get videos that look like they were shot on a real camera, not sketched by a robot",
      "Added a Founder / admin dashboard to fine-tune what shows up in the Studio without needing to touch code",
    ],
  },
  {
    version: "1.19.0",
    date: "2026-07-02",
    changes: [
      "Passwordless sign-in — enter your email and we'll send you a one-time secure link. Old paste-and-you're-in login is gone, so your account is safe even if someone knows your email address",
      "Studio Founder Lifetime buyers now get unlimited access the instant Pinball fires — the webhook auto-flags you as a Founder so there's no waiting for a manual grant",
      "AppSumo redemption + auto-provisioning is live — buyers get their tier, entitlements, and BYOK toggle set the moment they redeem their license key",
      "Tier names cleaned up — Starter ($49) / Pro ($179) / Pro Plus ($349) / Founder. The phantom 'Creator' name that never matched a real product is retired",
      "Founder members keep unlimited access to everything — no quotas, no changes",
    ],
  },
  {
    version: "1.18.4",
    date: "2026-07-01",
    changes: [
      "Faceless scene stills now generate through Gemini Nano Banana instead of Flux — more professional photorealism, lower cost, comes off the Emergent Universal Key balance instead of fal.ai per-call billing",
      "Content-hash cache preserved so identical scenes still return instantly on regenerate",
      "Flux stays as a silent fallback if Nano Banana ever rate-limits, so renders don't crash mid-pipeline",
      "'AI' source pill relabeled 'AI Still' to set the right expectation — this is a photograph, not motion video (motion is coming as a separate premium lane)",
      "Roadmap Faceless mode blurb updated to reflect the new stock-first + Nano Banana workflow",
    ],
  },
  {
    version: "1.18.3",
    date: "2026-06-30",
    changes: [
      "Fixed: Avatar renders with long scripts were failing at 45% with a wall of raw HeyGen error JSON. HeyGen's API caps script text at 5,000 characters (about 750 words) — we now catch this BEFORE submitting so you see a clean, friendly hint instead",
      "New: live character counter next to the script textarea in Studio shows exactly how close you are to the 5,000-char cap (muted → amber near limit → red over)",
      "New: always-visible mode-limit hint next to the 'Script' label — Avatar: 5,000 chars (~750 words) · Faceless: any length",
      "The friendly-error text and the hint both recommend switching to Faceless mode when Avatar is too short for your content — Faceless has no character limit because its voiceover is chunked scene-by-scene",
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
      "Tier names refreshed — Starter / Pro / Pro Plus (Founder badge unchanged for our OG legacy members)",
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
