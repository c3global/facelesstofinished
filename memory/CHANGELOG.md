# Faceless to Finished — What's New

A running log of every customer-visible change shipped to the app. Most recent
first. Plain English — if you're a customer reading this, this is for you.

> Want internal product-spec depth? See `PRD.md` (internal-only — that's where
> admin tooling, webhooks, backend plumbing, and migration scaffolding lives).

> **For developers / agents working on this app**: this file plus
> `/app/frontend/src/changelog.js` MUST be updated on every deploy. The footer
> popup in the app reads from `changelog.js`. See PRD.md for the workflow rule.

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
