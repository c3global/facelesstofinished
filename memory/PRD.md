# F2F48 Studio — Product Requirements Doc

## Original problem statement (verbatim from user)
Rebuild the Studio feature of the F2F48 (Faceless to Finished in 48) app off
Netlify Functions onto a portable React + FastAPI + MongoDB stack. The
Studio takes a script and renders a finished MP4 either with a HeyGen
avatar talking head + voice (Avatar mode) or a faceless slideshow with
TTS voiceover + B-roll from stock libraries (Faceless mode). Visual target
is Jogg.ai / HeyGen — compact pill "chips" below the script that each open
a contained modal with category tabs, search, and internal scroll.

User constraint: deployment target is Netlify (NOT emergent.sh). Be
frugal with API spend during development. Keep the source-of-truth for
paying customers + entitlements on the existing Netlify backend at
`https://faceless48.c3global.co/api/auth-me` — the new Studio should call
back to it for entitlement verification.

## Architecture

| Layer | Tech | Notes |
|---|---|---|
| Frontend | React (CRA), react-router-dom, axios, lucide-react | `/app/frontend` |
| Backend  | FastAPI, motor (async Mongo), httpx, PyJWT, emergentintegrations | `/app/backend` |
| DB       | MongoDB | `db.renders`, `db.activity`, `db.cache` |
| Auth     | JWT (HS256) issued after passing either (a) DEV_BYPASS_EMAIL check or (b) Netlify `/api/auth-me` cookie forward | 24h TTL |
| LLM      | Emergent Universal LLM Key → Claude Sonnet 4.5 (script generation, not yet wired into UI — Phase 2) | |
| Avatars/Voices | HeyGen v2 API (avatars + voices) — cached 24h in `db.cache` | |
| TTS      | Curated Kokoro voice list (10 voices) — fal.ai Kokoro endpoint (Phase 2 for real rendering) | |
| Stock    | Pexels Videos + Pixabay Videos APIs | |
| Renders  | Simulated pipeline (`DRY_RUN_RENDERS=true`) — walks status stages and returns sample MP4. Real pipeline wiring deferred to Phase 2 | |

## User personas
1. **Charity (admin/owner)** — paid customer with `studio` entitlement;
   needs the Studio to feel professional and let her get a final MP4 in
   under 3 minutes with minimal fiddling.
2. **Course buyer (base/shorts only)** — sees a locked Studio CTA in
   header; not in scope for Phase 1 UI.

## Core requirements (static)
- Email-allowlist passwordless login backed by Netlify auth-me; JWT cookie session on Studio.
- Mode switch (Avatar / Faceless) as segmented pill.
- Large script textarea is the primary input.
- Chip row underneath: Avatar/Voice or TTS-Voice/B-Roll, Aspect, Captions.
- Each chip opens a contained modal with tabs + search + internal scroll.
- Captions ON by default for 9:16, OFF by default for 16:9 (auto-flip until user touches).
- Faceless mode auto-suggests one scene per script paragraph; user can add/remove/edit.
- Per-scene stock picker (Pexels / Pixabay) with duration overlay + source badge on thumbnails.
- Storyboard preview strip above the Generate CTA.
- Single big Generate CTA — copy must NOT expose vendor names.
- Render-card with progress bar + status label + final MP4 player.
- Recent renders list with mode chip, status chip, date, play, delete (delete blocked while in-progress).

## What's been implemented (2026-01-12)
- ✅ FastAPI backend with auth (DEV_BYPASS + Netlify cookie forward), JWT issuance, studio-entitlement gate
- ✅ HeyGen avatars endpoint (1281 avatars live) + voices endpoint (2337 voices live), both cached 24h
- ✅ Kokoro TTS voice list (10 curated)
- ✅ Pexels + Pixabay stock-video search endpoints
- ✅ Render lifecycle (POST /studio/render → background task → status polling → complete with sample MP4 via DRY_RUN)
- ✅ Render history + delete
- ✅ Mongo-backed activity log of studio_render / studio_render_deleted events
- ✅ React frontend: Login (passwordless), Studio page with full chip-modal pattern
- ✅ Six picker modals: Avatar, Voice (HeyGen), TTS Voice (Kokoro), B-Roll Source, Aspect, Captions, Stock
- ✅ Captions auto-flip on aspect change with sticky override
- ✅ Auto scene generation from script paragraphs (faceless mode), storyboard preview strip
- ✅ Backend tests (15/15 pass), Frontend Playwright E2E (16/16 scenarios pass) per `/app/test_reports/iteration_1.json`

## Iteration 2 — Brand/UX (2026-01-12)
- ✅ Brand restyle to user's F2F48 palette (deep navy purple bg, rose-gold/copper warm accent, red CTA gradient, purple selection states)
- ✅ Header now uses real F2F48 logo image (`/logo-dark.png` and `/logo-light.png`) that swaps with theme toggle
- ✅ Dark/light theme toggle in header, persisted in localStorage
- ✅ Avatar vs Faceless mode visually differentiated: Avatar = warm copper accent, Faceless = purple accent (mode toggle, eyebrow color)
- ✅ Bulk B-Roll prompts textarea — one prompt per line auto-creates one scene card, capped at 12 with live count "3 scenes · up to 12"
- ✅ Per-scene source override pills (AI / Pexels / Pixabay) — default to global B-Roll chip, override per scene
- ✅ "Mix per scene" global option forces explicit per-scene source picks
- ✅ Source badges (AI / Px / Pb) on storyboard thumbnails
- ✅ Removed redundant "Add scene" / "Pick footage" / inline scene-number-remove UI
- ✅ Frontend Playwright E2E (~30 scenarios pass) per `/app/test_reports/iteration_2.json`

## Iteration 3 — Script Engine + Claude prompts (2026-01-12)
- ✅ Script Engine fully ported from legacy Netlify build at `/scripts` route
  - Long-form mode (gated by `base` entitlement) with Short/Medium/Long length presets
  - Shorts mode (gated by `shorts` entitlement) with YouTube/Reels/TikTok platform presets
  - Optional angle bias input
  - "Cut into a Short" repurposes a long script via a new Claude call
  - "Send to Studio" hands the narration off via localStorage to pre-fill Studio's script box
  - Section cards rendered from `### header` parsing; Copy button per section
  - History list, open, delete
- ✅ "Generate from script" button next to Studio's bulk B-roll textarea — Claude returns 4-12 visual prompts that auto-fill the textarea
- ✅ All Claude calls use the Emergent Universal LLM key (`claude-sonnet-4-5-20250929`)
- ✅ System prompts (`prompts.py`) ported verbatim from legacy so the section-header structure stays identical and the legacy parser keeps working

## Iteration 7 — Script Engine 2.0 (2026-01-12)
Major refactor that addresses 7 explicit user asks. Verified 21/21 backend + ~95% frontend across two test passes (iteration_7.json + iteration_8.json).

**Two-step gated flow.** `/api/scripts/angles` is a new, fast (~5-8s) sync endpoint that returns 4 distinct creative angles for a topic, each tagged with category (`curiosity` / `contrarian` / `how-to` / `story` / `list`). The full script package (`/api/scripts/long` and `/scripts/shorts`) now accepts a `chosen_angle` dict and explicitly tells Claude to skip the "TOPIC ANGLES" section and commit fully to the locked angle. The UI is a state machine — `TOPIC → ANGLES → GENERATING → RESULT`.

**Saved Angles backlog.** `db.saved_angles` collection keyed by user_email; CRUD at `/api/scripts/saved-angles`. Each angle card has a bookmark icon (BookmarkCheck when saved). A "Show saved angles (N)" toggle reveals a panel of saved angles — one click loads the topic + angle and jumps straight to generation.

**Markdown rendering** via `react-markdown` + `remark-gfm`. Section card bodies render `**bold**`, lists, headings, code, blockquotes, and tables as proper HTML instead of raw asterisks. Brand-aligned typography.

**Skeleton placeholders + elapsed counter.** During step-2 generation, each expected section renders a shimmer-animated skeleton card with a live "Generating · {N}s" label. When the job completes, the result snaps in.

**"Copy all" button + toast.** Copies the entire markdown script package to the clipboard. Falls back to `document.execCommand('copy')` if `navigator.clipboard` isn't available (improves sandbox / headless behavior). Toast confirms "Copied entire script." and auto-dismisses.

**Rotating tagline.** Hero h1 randomly picks one of three on mount: "Write a script that gets watched.", "Type a topic. Get a complete script.", "From blank page to ready-to-record — in seconds."

**Platform color theming (Shorts).** `--platform-accent` CSS variable set at the document root via `document.documentElement.style.setProperty()` based on the selected platform: YouTube `#FF0033`, Reels `#E1306C`, TikTok `#25F4EE`. Applied to: platform-card selected state, Generate CTA gradient, phone-frame chrome + glow, status-bar platform badge, beat-label color, on-screen cue background, and section-column headers in Shorts mode. Long-form mode actively removes the variable so the brand purple takes over.

**Phone-frame wrapper (Shorts).** New `<PhoneFrame platform={p}>` component renders a 320px phone shell with notch, fake 9:41 status bar, platform pill (TIKTOK / REELS / YOUTUBE) and a 22px-radius screen. Shorts result lays out in a 3-column Plan / Script / Distribute grid — Plan column has Hook Variations + Title Variants + Cover Image Prompts; Script column centers the phone containing parsed HOOK/BODY/CTA beat blocks with inline `[ON-SCREEN: ...]` and `[B-ROLL: ...]` cues styled as platform-tinted chips; Distribute column has Caption, Hashtags, On-Screen, B-Roll list, Notes.

**Parser hardening.** Two real Claude-quirk fixes shipped in this iteration:
- `parseSections()` now accepts any heading level (`#{1,6}`) and only starts a new section when `classify(title)` resolves to one of 14 known top-level keys. Sub-headings like `### Trap #1` inside the FULL NARRATION SCRIPT fold into the parent section's body instead of starting an orphan section. Regression test in `/app/frontend/src/utils/parser.test.cjs`.
- `ShortPhoneBody` strips leading/trailing markdown emphasis (`**`, `*`) from each line before the beat-marker regex test, so `**[HOOK — 0:00–0:03]**` is detected correctly. Verified against real shorts job from history.

**Files touched**
- `/app/backend/server.py` — new `/scripts/angles`, saved-angles CRUD, `_angle_clause()` helper, `LongScriptRequest.chosen_angle` + `ShortsRequest.chosen_angle`.
- `/app/backend/prompts.py` — new `ANGLES_SYSTEM_PROMPT` and `build_angles_user_message`. Long + shorts prompts no longer emit a TOPIC ANGLES section.
- `/app/frontend/src/pages/Scripts.jsx` — full rewrite (state machine, AngleCard, SectionCard, SkeletonCard, ShortPhoneBody, copyAll with execCommand fallback, applySavedAngle, tagline rotation, platform accent useEffect).
- `/app/frontend/src/components/PhoneFrame.jsx`, `/app/frontend/src/components/Toast.jsx` — new.
- `/app/frontend/src/utils/parser.js` + `parser.cjs` — heading-level fix, narration extractor unchanged.
- `/app/frontend/src/utils/parser.test.cjs` — added SAMPLE_MIXED_HEADINGS regression test.
- `/app/frontend/src/index.css` — new `--cat-*` variables, `--platform-accent` token.
- `/app/frontend/src/App.css` — appended ~250 lines: `.toast`, `.angle-card`, `.angles-grid`, `.saved-angle-card`, `.skeleton-bar` w/ shimmer, `.markdown` rules, `.platform-card.is-selected` using `--platform-accent`, `.shorts-layout`, `.phone-wrap` / `.phone-shell` / `.phone-status` / `.phone-platform-badge` / `.phone-beat-*` / `.phone-cue-onscreen` / `.phone-cue-broll`.

**Deferred (acknowledged in test report)**
- Scripts.jsx is now ~800 lines — recommend extracting AngleCard / SectionCard / SkeletonCard / ShortPhoneBody to `/app/frontend/src/components/scripts/` next iteration.
- Saved-angles endpoint has no per-user max cap or rate limit (suggest 200/user soft cap + unique index on `(user_email, angle.name, topic)`).
- ✅ New `extractNarration(rawScript)` helper in `/app/frontend/src/utils/parser.js`:
  - Prefers the `FULL NARRATION SCRIPT` (long) or `SHORT-FORM SCRIPT` (shorts) section
  - Strips inline `[B-ROLL: ...]` and `[ON-SCREEN: ...]` directive cues
  - Strips markdown bold/italic markers (CRITICAL: must run BEFORE bracket-strip because Claude wraps beat headers in `**...**`)
  - Strips standalone bracket beat headers like `[HOOK — 0:00–0:30]`, `[SECTION 1: ...]`, `[OUTRO + CTA — ...]`
  - Collapses whitespace into clean paragraphs
- ✅ New `extractBrollPrompts(rawScript)` helper pulls bulleted prompts from the consolidated `B-ROLL SHOT LIST` section, strips markdown/bullet formatting, caps at 12.
- ✅ Handoff payload is now JSON `{ script, brollPrompts, sourceMode, topic, ts }` (was a plain string). Backward-compat: Studio's handoff useEffect still reads a plain string from older versions.
- ✅ Smart mode default on handoff: Shorts source → auto-switch to Faceless mode (uses voiceover + B-roll natively); Long source → stay on Avatar but stage the B-roll prompts so flipping to Faceless preserves them.
- ✅ Transient handoff banner on Studio shows word count + B-roll prompt count + topic + a one-click "Switch to Faceless to use the B-roll prompts" CTA when in Avatar mode with prompts staged. Auto-dismisses in 10s.
- ✅ Unit test at `/app/frontend/src/utils/parser.test.cjs` covers bold-wrapped bracket beat headers as a regression guard. Verified: 100% frontend pass via testing agent on the public preview URL (`/app/test_reports/iteration_6.json`), with a fresh real-Claude long-form generation producing 5,694 chars of pristine narration and 12 B-roll prompts.

**Deferred from this iteration (Avatar + B-roll cutaways composite mode):** A true "Avatar + B-roll cutaways" render mode (HeyGen avatar talking head intercut with stock B-roll) needs a new backend render branch and a UI toggle in Avatar mode. Decision: defer until the real HeyGen/fal.ai pipelines are wired (DRY_RUN_RENDERS=false) so the UI isn't building against simulated output. The B-roll prompts ARE staged on the handoff so the user can manually flip to Faceless mode in the meantime.

## Prioritized backlog

### P0 — must-have for Phase 2
- Wire real HeyGen v2 video generation pipeline (avatar mode end-to-end with 9:16 + captions on)
- Wire fal.ai Kokoro TTS + Flux + ffmpeg-compose pipeline (faceless mode)
- Cross-origin auth handoff with Netlify: real cookie forward path tested + deployed under `studio.c3global.co` OR Netlify reverse-proxy
- Avatar gallery virtualization (1281 entries is heavy)

### P1 — important
- Favorites + recently-used for avatars and voices (user-specific)
- Script Engine port from legacy Netlify (Claude streaming, sections, repurposer)
- Admin port from legacy Netlify (buyers / activity / stats)
- Real-time progress over SSE instead of polling

### P2 — nice-to-have
- Save render presets ("my brand defaults")
- Multi-platform repurpose: take one render and produce Shorts variants
- Cost/credit tracking per user
- Render queue concurrency limit per user

## Next tasks (handoff)
1. Wire the real HeyGen pipeline behind `DRY_RUN_RENDERS=false` toggle (gated by env flag for safety)
2. Wire the real fal.ai Kokoro + Flux + ffmpeg compose pipeline
3. Add the auth cookie-forward path verification once Studio is on `studio.c3global.co`
4. Port Script Engine + Admin from `/app/legacy_netlify/`
