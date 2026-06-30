# Faceless to Finished — What's New

A running log of every customer-visible change shipped to the app. Most recent
first. Plain English — if you're a customer reading this, this is for you.

> Want internal product-spec depth? See `PRD.md` (internal-only — that's where
> admin tooling, webhooks, backend plumbing, and migration scaffolding lives).

> **For developers / agents working on this app**: this file plus
> `/app/frontend/src/changelog.js` MUST be updated on every deploy. The footer
> popup in the app reads from `changelog.js`. See PRD.md for the workflow rule.

---

## v1.12.0 — June 30, 2026

- **NEW: API Keys settings page** for Pro Plus + Founder members — plug in
  your own **Anthropic**, OpenAI, HeyGen, and fal.ai keys and your scripts,
  thumbnails, and video renders draw from your own provider quotas instead
  of ours.
- **Anthropic key** unlocks the Script Engine + thumbnail prompt rewriter on
  your own Claude quota — every script generation routes through your key
  when one is saved.
- Keys are **encrypted at rest** (Fernet symmetric AES-128 + HMAC) and never
  displayed back to the dashboard after save — you only see a safe preview
  like `sk-…0abc`.
- **Thumbnails — click any image in your gallery** to open a full-screen
  preview with Download + Copy prompt actions right there (no more right-
  clicking to save).
- Find the API Keys page in your **Profile menu → API keys**. Each key can
  be replaced or removed at any time; renders silently fall back to
  platform keys when no customer key is saved.

---

## v1.11.0 — June 30, 2026

- **Profile dropdown menu** in the header — quick access to your tier label,
  redeem codes, and sign out from one place.
- **NEW: Code redemption flow** — paste any access code on the dedicated
  **Redeem** page (reachable from a "Have a redemption code?" footer link,
  an "I have a code instead" toggle on the login screen, and a "Redeem code"
  item in the Profile dropdown). Generic by design: works for any code,
  doesn't reveal the channel it came from.
- **Tier names refreshed** — **Starter** / **Creator** / **Pro** / **Pro Plus**
  (legacy Founder badge unchanged for our OG members).
- **Founders now get a subtle copper accent** throughout the app + a
  small "Founder" badge in the header. Quiet, exclusive, recognizable.
- **Upgrade button appears in the quota popover** when you're running low
  on renders. Routes you to the right place automatically (no broken links
  while we're between campaigns).

---

## v1.10.2 — June 30, 2026

- **Fixed**: "Make thumbnail" now correctly extracts your 3 cover concepts
  from long-form scripts. The parser was silently failing on Claude's
  markdown bold-wrapping of numbered list items (`**1. [Label]**`),
  falling back to a truncated chunk of narration instead. Stripped all
  `**` markers before regex matching — picker now populates cleanly for
  every script that contains the cover-prompts section.
- Cover concepts picker now shows all 3 options with their matching title
  variants — pick the one you want, or hit **Generate all 3** to compare.

---

## v1.10.1 — June 30, 2026

- Long-form scripts now get 3 **Title/Thumbnail variants** + 3 **Cover Image
  Prompts** (matches what Shorts has had all along).
- Click **Make thumbnail** on any new script and you'll see a picker of 3 cover
  concepts — choose the one you like, or hit **Generate all 3** to compare
  them side-by-side.
- Dramatically upgraded the thumbnail rewriter — every prompt now bakes in
  viral YouTube thumbnail rules: expressive focal subject, bold color palette,
  dramatic cinematic lighting, clear space for overlay text.
- Final image prompts get a hidden viral-style boost suffix before they hit
  OpenAI — more "top creator" production quality, less stock-photo flat.
- Confirmation prompt when you hit **Generate all 3** on a quota-bound tier —
  never burn 3 slots by accident.

> **Note for early users:** Long-form scripts you generated *before* this
> update won't have cover prompts. Re-generate the script to get the new
> sections, or hit **Make thumbnail** anyway — we'll fall back to extracting
> your hook so you still get a usable starting point.

---

## v1.10.0 — June 30, 2026

- **NEW: Thumbnail Engine** — generate click-worthy YouTube and Shorts thumbnails
  right inside Faceless 48. Pick **Premium** for hero shots or **Fast** for quick
  A/B testing.
- Built-in prompt rewriter — type a casual idea and tap **Rewrite for me** to get
  a vivid, image-ready prompt.
- Three aspect ratios baked in: **16:9** for YouTube, **9:16** for Shorts / Reels /
  TikTok, **1:1** for Instagram feed.
- **Make thumbnail** button in the Script Engine result view sends your script
  topic + opening hook straight into the new tool.
- Find **Thumbnails** as a top-level tab in the header alongside Script Engine
  and Studio.

---

## v1.9.0 — June 30, 2026

- New render-budget pill in the Studio header — see how many renders you've
  used this cycle and when your next batch unlocks at a glance.
- Click the pill for the full breakdown: total renders, Avatar sub-cap
  (Studio Pro+), and your exact cycle reset date.
- Friendlier message when you've used your last render — no more cryptic 402s.

---

## v1.8.1 — June 29, 2026

- **What's New popup** now nudges you with a subtle amber dot when there's a
  release you haven't seen yet — opens the popup once to dismiss.
- Last-seen timestamps now update accurately on every sign-in (was only
  tracking imports and webhook events before).

---

## v1.8.0 — June 29, 2026

- Resource Library is back — five production guides (Voiceover, B-Roll,
  Thumbnail, Production Map, Publishing Checklist) live in the new **Resources**
  tab.
- Fixed an issue where long Faceless videos sometimes failed at the voiceover
  step.
- **What's New** popup added to the footer (this one) — every update will land
  here from now on.

---

## v1.7.0 — June 25, 2026

- **Compare-all view** for multi-platform shorts — see YouTube, Reels, and
  TikTok side-by-side in their signature colors.
- **Per-platform Send-to-Studio** button under each phone in compare view — one
  click to pick your winner.
- New **New short / New script / New sprint** button in the result toolbar so
  you can start fresh without changing modes.
- Recent scripts list now filters by current mode (Shorts hides Long-form,
  with a pill row to toggle).
- Phone rim color now matches the loaded script's platform — Reels = fuchsia,
  TikTok = teal, YouTube = red.
- YouTube cell now renders ON-SCREEN / B-ROLL chips correctly.
- TikTok captions are easier to read — switched to dark ink for legibility.
- Cleaner result-page layout — Production Notes and Cover Image Prompts now
  align side-by-side.
- Better color coding across script sections — B-Roll is green, On-Screen
  Text is cyan, Cover Image Prompts is orange.

---

## v1.6.0 — June 19, 2026

- **Faster Faceless renders** — voiceover now generates in parallel with
  visuals (10-15 seconds saved per render).
- **Smarter B-roll selection** — stock footage now actually matches your
  script (was getting distracted by camera-direction keywords).
- Higher-quality stock footage — 720p floor, 1080p ceiling (no more soft
  480p clips).
- **Star your favorite voices** — pinned to the top of every tab plus a
  dedicated ★ tab.
- **Star your favorite avatars** — same star-toggle pattern across the full
  HeyGen catalog.
- Voice picker now has a **Neutral** tab (76 voices that were previously
  hidden).
- Custom voice uploads now show up correctly in the picker.
- Avatar picker no longer gets stuck loading.
- Hook variations render cleanly without spurious blank lines.
- Copy Script preserves formatting (green B-roll cues, amber scene headers)
  when pasted into Google Docs, Notion, or Word.
- Watch your script form live — progressive rendering with phase-aware
  status banner.
- Three new long-form toggles: include/exclude Hook Variations, B-Roll Shot
  List, Production Notes.

---

## v1.5.0 — June 13, 2026

- Redesigned login page with a landing-style hero introducing what Faceless
  to Finished is.
- Returning vs. first-time login experience — copy adapts automatically.
- New 4-device hero mockup with a subtle purple/amber glow.
- Light mode hero gradient now reads cleanly on near-white backgrounds.
- Welcome toast on first sign-in after purchase.
- Result page redesigned as a **bento grid** — phone hero at the top, eight
  result cards below in a responsive 3-column layout.

---

## v1.4.0 — June 11, 2026

- **Two-step script generation** — first see 4 distinct creative angles
  (Curiosity, Contrarian, How-To, Story, List), then commit to the one you
  want.
- **Sprint mode** — generate 5 variants of the same short in one click for
  A/B testing.
- **Saved angles** — bookmark any angle and recall it later.
- **Cut into a Short** — repurpose any long-form script as a Shorts script
  in one click.
- **Send to Studio** handoff — one click from script to video render with
  B-roll prompts pre-filled.
- **Multi-platform Shorts** — generate YouTube + Reels + TikTok variants
  together, each tuned for that platform.

---

## v1.3.0 — May 29, 2026

- **Studio launched** — Avatar mode (HeyGen avatar talking head + voiceover)
  and Faceless mode (AI voiceover + B-roll slideshow).
- Six picker modals: Avatar, Voice (HeyGen), TTS Voice, B-Roll Source,
  Aspect, Captions — each with tabs, search, and scrolling.
- Captions auto-flip — ON for 9:16, OFF for 16:9 — with a sticky override.
- Auto scene generation from script paragraphs (up to 12 scenes).
- Per-scene B-roll source override (AI / Pexels / Pixabay) with a "Mix per
  scene" option.
- **Three thumbnail previews per scene** — see candidates and pick your
  favorite before render.
- **Bring your own B-roll** — upload screen recordings, images, or
  screenshots and we'll animate them in.
- **Record your own voiceover** in the browser if you don't want AI TTS.
- Caption burn-in with Top / Bottom / Center placement.
- Inline video player — watch finished renders inside the app without
  opening a new tab.
- Run multiple renders at once with live per-scene status ("Stitching scene
  4 of 5…").

---

## v1.2.0 — May 26, 2026

- **Script Engine launched** — Long-form (with Short / Medium / Long length
  presets) and Shorts (with YouTube / Reels / TikTok platform presets).
- Optional angle bias input to nudge the script in a specific creative
  direction.
- Section cards for the generated output — copy any section individually or
  the whole thing at once.
- History sidebar with open/delete for every script you've generated.

---

## v1.1.0 — May 23, 2026

- Dark / light theme toggle in the header, persisted across sessions.
- Brand restyle to the deep-navy + rose-gold + red palette.
- Avatar mode painted in warm copper, Faceless mode in purple, so you always
  know which pipeline you're in.

---

## v1.0.0 — May 21, 2026

- **Faceless to Finished is live on the new platform** — passwordless email
  sign-in, JWT session, and entitlement-gated access.
- Initial Script Engine and Studio scaffolding in place — first deploy.

---

*Last updated: June 29, 2026 · See `/app/frontend/src/changelog.js` for the
in-app footer source of truth.*
