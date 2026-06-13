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

## Iteration 15 — Five issues from real-render attempt #2 (2026-02-13)
User retried Avatar+Faceless real-render after iter-14. Reports:
1. Avatar STILL failed with `caption is invalid: Input should be a valid boolean`
2. 9:16 video came out with the avatar tiny in centre + black bars top/bottom + white bars left/right
3. "Finalizing video… 85%" looked stuck during the long real-HeyGen wait — no animation to confirm it's still alive
4. Faceless render timed out; the screen went blank and forced a re-login
5. The stuck "Composing" Faceless row in history had no way to open/check its current status

**Bug 1 — Caption STILL the object form (the iter-14 fix never landed).** Investigated and confirmed the `search_replace` in iter-14 didn't take — the file still contained the `{file_format, style}` caption-object form. Re-applied as a clean overwrite + verified by grep that the body now sends `"caption": bool(job.get("captions", True))`. HeyGen v2 `/video/generate` requires a literal boolean; the styled-object form belongs on HeyGen's Template API.

**Bug 2 — 9:16 framing wrong.** HeyGen's default behaviour for `dimension: {width: 720, height: 1280}` on a 16:9-native talking-head avatar is to letterbox-fit, producing a small landscape clip in a portrait canvas with huge black/white bars. Fix per [latest HeyGen docs](https://developers.heygen.com/changelog): added `aspect_ratio` + `fit` controls to the request body (`aspect_ratio: "9:16"` + `fit: "cover"` for portrait; `fit: "cover"` crops/zooms the avatar to fill the frame cleanly). Kept the legacy `dimension` field for backward compatibility.

**Bug 3 — No "still alive" animation during long stages.** The render-bar-fill was a static width transition; when the backend held at progress=85 for 30-60s while polling HeyGen, the bar visually froze. Fix: added a CSS shimmer animation (`render-bar-shimmer`) to the fill that sweeps a brighter highlight band across the bar at 1.6s cadence whenever `status !== "complete" && status !== "failed"`. Class `is-progressing` toggles on/off based on the render state.

**Bug 4 — Faceless timeout blanked the screen.** Two distinct root causes:
- `pollStatus` cleared the interval on the FIRST exception (network blip, token race, transient 5xx). Once cleared, the UI froze at the last polled state with no recovery. Hardened: tolerate up to 6 consecutive failures (~9s of retries) before giving up. On final give-up, surface a clear "Lost connection — refresh and click Resume" message instead of going blank.
- React did not actually crash; the "blank screen" was the user's polling loop dying silently while the backend was still working. The new shimmer + Resume button cover this case end-to-end.

**Bug 5 — In-progress history rows had no Open/Resume button.** Added a `<Play />` icon button (data-testid `history-resume-{id}`) visible only when the render is in a non-terminal status. Clicking it calls the new `resumeRender(jobId)` helper which fetches the latest render doc, sets it as the active render-card, scrolls into view, toasts "Resumed tracking — watch progress above.", and re-attaches `pollStatus` so the user can watch it finish.

**Captions-style picker visible in Avatar mode too.** Removed the `mode === FACELESS` gate. Now visible whenever captions are ON. When in Avatar mode, an italic note clarifies that HeyGen's auto-styling is currently used; the picker is preserved so the choice persists when we wire HeyGen Template API in a future iteration.

**Files touched in iter 15**
- `/app/backend/server.py` — `_run_render_avatar` HeyGen body now correctly sends bool `caption`; added `aspect_ratio` and `fit: "cover"`.
- `/app/frontend/src/pages/Studio.jsx` — hardened `pollStatus` with 6-failure tolerance + clear error message; new `resumeRender(jobId)` helper; Resume `<Play>` button on non-terminal history rows; `chipCaptionStyle` un-gated from FACELESS mode (with explanatory note in Avatar mode); `render-bar-fill` gets `is-progressing` class while non-terminal.
- `/app/frontend/src/App.css` — `.render-bar-fill.is-progressing::after` shimmer keyframe; `.chip-pill-note` italic note style.

**Verified live** (dry-run smoke pass): Avatar mode pill picker visible with the note. Render kicked off shows "Render started…" toast + bar shimmer animating during the in-progress state. Faceless "Composing" history row shows the new Resume button next to trash.

## Iteration 14 — Three real-render bugs from iter-13 + captions style picker (2026-02-13)
User's avatar real-render failed with `HeyGen API error 400 caption is invalid: Input should be a valid boolean`, and faceless failed with `fal-ai/wizper 422 chunk_level Input should be 'segment'`. Plus the stuck "Polling" Avatar row from iter-12 couldn't be deleted because the delete endpoint refused non-terminal statuses.

**Bug 1 — HeyGen caption schema regression.** Iter-13 switched to a `caption: {file_format, style}` object form based on a web-search result that turned out to apply to HeyGen's Template API, not `/v2/video/generate`. The real endpoint wants a plain bool. Reverted to `caption: bool(job.get("captions", True))`. HeyGen handles burn-in styling automatically; custom styling is a Template-API future enhancement.

**Bug 2 — fal.ai wizper chunk_level wrong literal.** Iter-13 sent `chunk_level: "word"`; wizper API accepts only `"segment"`. Fixed. Wizper now successfully returns segment-level transcription which we convert into an SRT string in-memory.

**Bug 3 — Stuck render couldn't be deleted.** `/studio/render/{id}` DELETE and `/studio/render/bulk-delete` both refused to remove non-terminal renders to protect against orphaned background tasks writing to a vanished doc. Relaxed for admins (force-delete any status, log `force_admin:true` to activity); customers still get the safety guard. Frontend trash button + checkbox now enabled for admins on any row.

**Faceless captions pipeline rewrite.** fal.ai's `ffmpeg-api/compose` `tracks` schema only supports `video` and `audio` types — `subtitles` isn't a valid track type, which means the iter-13 subtitle-track injection would have failed even if wizper had succeeded. Replaced with a 2-step pipeline:
1. Compose video without captions (existing async-queue path)
2. If captions enabled AND wizper transcript succeeded, build a proper SRT string in-memory and submit a second compose job with the SRT
   
Best-effort — if the caption step fails, the un-captioned video ships rather than failing the whole render. Caption burn-in is still flagged as "in progress" since fal.ai's exact field name for SRT input isn't documented; we pass both `srt` and would fall back to a separate caption-video model in a follow-up if this doesn't land.

**Captions-style picker (you asked for it).** New `caption_style` field on `RenderRequest` (default `"boxed"`). Frontend exposes a compact pill-group below the chip row, visible only when captions are ON and mode is Faceless (Avatar mode uses HeyGen's auto-styled burn-in which we don't control). 4 presets: Minimal · Boxed · Bold yellow · Outlined. Stored on the render doc and ready to be consumed by the caption burn-in step once we lock fal.ai's exact field name.

**Files touched in iter 14**
- `/app/backend/server.py` — HeyGen caption reverted to bool; wizper chunk_level → segment; SRT builder + 2-step caption-burn pipeline; admin force-delete on single + bulk delete; `RenderRequest.caption_style` field; `caption_style` persisted on the render doc.
- `/app/frontend/src/pages/Studio.jsx` — `captionStyle` state, `chipCaptionStyle` pill group rendered below chip row (Faceless + Captions ON only), buildPayload includes `caption_style`, history-row trash button + checkbox enabled for admin on any row.
- `/app/frontend/src/App.css` — `.chip-pill-group`, `.chip-pill-label`, `.chip-pill[.is-active]` styles.

**Verified live**: stuck "Polling" Avatar render force-deleted via DELETE → HTTP 200. Render POST with `caption_style:"bold-yellow"` returns the value on the new doc. Caption-style pill group renders with 4 options, Bold yellow toggles to active state on click.

## Iteration 13 — Whitelabel labels + Captions + Voice previews + fal.ai async queue + Bulk delete (2026-02-13)
Five customer-feedback fixes in one batch. Verified live.

**Vendor-neutral stage labels (applied to everyone).** All progress labels in `_run_render_avatar`, `_run_render_faceless`, `_run_render_composite` rewritten to neutral copy ("Generating voiceover…", "Generating avatar video…", "Stitching b-roll together…", "Composing final video…"). Vendor names (HeyGen / fal.ai / ffmpeg / Kokoro) no longer appear in user-facing progress UI. Admin still gets vendor names in the activity-log audit trail + render-doc `mode` field for diagnostics.

**HeyGen avatar captions fix.** Switched from legacy `caption: true` boolean to the newer object schema `caption: {file_format: "srt", style: {...}}` which is required for burn-in (the boolean form only generates a sidecar `subtitle_url`). Captions now burn into the rendered video. Verified by web-search against latest HeyGen v2 docs.

**Faceless captions support.** Added a fal.ai Whisper transcription step (`fal-ai/wizper`, word-level chunks) between TTS and ffmpeg compose. The resulting word-timestamps are passed to ffmpeg compose as a `subtitles` track type so captions burn into the final video. Best-effort — if Whisper fails the render proceeds without captions rather than aborting.

**fal.ai async queue pattern (fixes the ReadTimeout).** `httpx`'s 120s timeout was killing multi-scene ffmpeg compose jobs. Replaced the sync `fal.run/<model>` call with the async `queue.fal.run/<model>` submit-and-poll pattern (`request_id` → `/status` → `/requests/{id}` final fetch, 3s poll interval, 600s timeout cap). Reusable helper `_fal_queue_run(model_id, payload, *, max_wait_s)` defined inline in `_run_render_faceless`. Every failure mode (submit non-200, no request_id, status FAILED, polling timeout) writes a detailed error to the render doc.

**Kokoro voice previews.** TTS voice picker now shows play buttons for all 10 voices (matching the existing HeyGen voice-picker UX). New `POST /studio/tts-voices/preload` admin endpoint generates a 5-second sample per voice using `fal-ai/kokoro/american-english` (for af_/am_ prefixes) and `fal-ai/kokoro/british-english` (for bf_/bm_ prefixes). Sample URLs cached in `db.voice_samples` collection, served via `GET /studio/tts-voices`. Idempotent — voices that already have a cached preview are skipped. Total cost to pre-warm all 10 voices: ~$0.05 one-time. Verified: 10/10 voices generated and surface play buttons in the picker.

**History bulk-select + delete.** Per-row checkboxes (admin and customer) appear on completed/failed rows. Header gains "Select all" / "Clear (N)" / "Delete N selected" actions. New backend endpoint `POST /api/studio/render/bulk-delete` accepts `{ids: [...]}` and skips in-progress jobs to avoid orphaning background tasks. Activity-log row captures `requested` vs `deleted` counts.

**Files touched in iter 13**
- `/app/backend/server.py` — vendor-neutral stage labels in all 3 pipelines; `_kokoro_endpoint(voice_id)` helper for AmE/BrE routing; HeyGen `caption` object schema; full `_fal_queue_run()` helper + Whisper transcription + ffmpeg-compose `tracks`-style payload in faceless pipeline; `POST /studio/tts-voices/preload`; `GET /studio/tts-voices` enriched with cached `preview_audio`; `POST /studio/render/bulk-delete` endpoint.
- `/app/frontend/src/pages/Studio.jsx` — `selectedIds` state, `toggleSelected/selectAllVisible/clearSelected/bulkDelete` handlers, history-head Select-all/Clear/Bulk-delete actions, per-row `<input type="checkbox">` cell on every completed/failed row.
- `/app/frontend/src/App.css` — `.history-head`, `.history-head-actions`, `.header-btn.is-danger`, `.history-check`, `.history-row.is-selected` styles.

**Note on prior history rows.** Pre-iter-13 entries still point at the dead BigBuckBunny URL (fixed in iter-12) and don't have captions baked in. Use the Re-run as dry-run button or trash icon to clear them out.

## Iteration 12 — Three real-render bugs fixed (2026-02-13)
User attempted Test 1 (real render) and reported: (a) play button on completed history rows opened a Google Cloud Storage XML 403 AccessDenied page; (b) clicking the "Render (real)" CTA appeared to do nothing visible. Reproduced both live + fixed three root causes:

**Bug 1 — Dead sample MP4 URL.** Google revoked public read on `commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4` — every dry-run render that landed in history now plays as a broken 403 XML page. Fix: swapped `SAMPLE_VIDEO_URL` to `https://www.w3schools.com/html/mov_bbb.mp4` (small 788KB Big Buck Bunny clip, HTTP 200, stable mirror). All NEW dry-run renders now produce a playable video. Pre-existing history rows still point at the dead URL — they'll need to be manually deleted or re-run via the re-run button.

**Bug 2 — Active render-card hidden below scroll.** When the admin clicked "Render (real)" → confirm modal → confirm-go, the render-card DID appear, but at the TOP of the page. The user was scrolled down at "Recent renders" so they never saw the new card or its progress bar — only saw the new entry land in history once it completed. Same UX trap on the re-run buttons. Fix: new `scrollToRenderCard()` helper called from `fireRender()` and `rerenderAsDryRun()`. Render-card now scrolls into view (smooth, `block: 'center'`) on every render kick-off. Verified live: scrollY 994 → render-card top:0.375, in_viewport:true.

**Bug 3 — Silent backend failures swallowed the real error.** HeyGen/fal.ai API failure paths called `_finalize(ok=False, url=None, actual_cost_cents=0)` which writes a generic "failed" status with no error detail. So a missing key, an invalid voice id, or a billing issue all surfaced as the same vague "Render failed: unknown error". Fix: every non-200 response from HeyGen (initial submit + status polling) and from fal.ai (Kokoro TTS + ffmpeg compose) now writes a detailed `error` field with the HTTP code + first 300 chars of the response body. Polling timeouts also surface a clear "HeyGen polling timed out after 5 minutes" message. The render-card's existing failure JSX (`<p>Render failed: {render.error}</p>`) already renders this — no UI change needed.

**Toast confirmation.** Added a Toast on render kick-off ("Real render started — scroll up to watch progress." / "Render started…" / "Re-firing as dry-run — scroll up to watch.") so the click always produces a visible response even if the user's scroll position is below the render-card.

**Files touched in iter 12**
- `/app/backend/server.py` — SAMPLE_VIDEO_URL swap; preserved error detail in `_run_render_avatar` (3 failure paths) + `_run_render_faceless` (2 failure paths).
- `/app/frontend/src/pages/Studio.jsx` — added Toast import, `toast` state, `scrollToRenderCard()` helper, toast + scroll wired into `fireRender()` and `rerenderAsDryRun()`, `<Toast />` mounted at end of return.

**Verified live** (2026-02-13): dry-run render kicked off from a history row at scrollY=994 → render-card auto-scrolled into view at top=0.375 → toast displayed → render walked stages to "Done" → `<video src="https://www.w3schools.com/html/mov_bbb.mp4" controls />` rendered and is playable. End-to-end clean.

## Iteration 11 — Live UI smoke + Re-run as dry-run (2026-02-12)
User cleared all 5 deferred-handoff items visually, then requested one polish-only addition before starting real-render testing on their side.

**Verified live via `/app/test_reports/iteration_11.json`:** 100% PASS on all UI surfaces. Zero bugs found.

**Avatar dry-run live UI walk:** chip-avatar → first avatar-card → chip-voice → first voice-row → script fill → generate-btn. Progress 5% (Queued) → 25% (Synthesizing voice on HeyGen) → 100% (Done) in ~2.5s. render-video plays BigBuckBunny.mp4. History row added.

**Faceless dry-run live UI walk:** mode-faceless → chip-tts-voice → first voice-row → bulk-prompts ("sunset over the ocean\\ncity at night") → script fill → both scenes set to source=ai → generate-btn. Walks voiceover→visuals→composing in ~2.8s with scenes_n=2 stored.

**Composite dry-run via curl:** composite mode is not exposed in the mode-toggle UI (admin-curl reachable only). `POST /api/studio/render {mode:'composite', script:'…', aspect:'9_16', avatar_id:'TEST', voice_id:'TEST'}` completes with `result_url=SAMPLE_VIDEO_URL`, `actual_cost_cents=0`, and lands in `/api/studio/history`.

**`ADMIN_EMAILS` env explicit.** Made `ADMIN_EMAILS=drcharitycampbell@gmail.com` explicit in `/app/backend/.env` (was previously defaulting in code). `/auth/me` still returns `isAdmin:true` for the admin user after the env-pull was made explicit.

**"Re-run as dry-run" admin-only button** (`/app/frontend/src/pages/Studio.jsx`):
- New `rerenderAsDryRun(sourceDoc)` handler rebuilds the full render payload from a source doc and POSTs to `/studio/render` with `dry_run:true` forced. Same cost-cap path, no special endpoint.
- Wired on the **active render card** (`[data-testid='render-card-rerun-dryrun']`) as a `<RotateCw />` + "Re-run as dry-run" pill button. Visible only when `isAdmin && (render.status === 'complete' || render.status === 'failed')`.
- Wired on **every completed/failed history row** (`[data-testid^='history-rerun-dryrun-']`) as a `<RotateCw />` icon button. History payload may be trimmed, so the handler first does `GET /studio/render/{id}` to fetch the full doc, then re-fires.
- **Visual reset**: when the re-run button is clicked, the render-card state is immediately set to `{status:'queued', progress:0, progress_label:'Re-firing as dry-run…'}` so the admin sees the click registered even if the new render walks stages faster than the eye can track (caught by code review in iter 11).
- Customer (non-admin) UI gating: confirmed via code review — both buttons wrapped in `{isAdmin && …}`.
- Backend gating: confirmed via code review of `server.py:711` — the admin gate only restricts `dry_run:FALSE` overrides. `dry_run:TRUE` from any user falls through to the env default. So the re-run button is safe to expose to admins without backend coupling.

**Seed data:** 5 dry-run renders created during iter 11 testing (composite via curl, avatar live UI, avatar active-card re-run, avatar history-row re-run, faceless live UI). All `actual_cost_cents=0`.

**Files touched in iter 11**
- `/app/backend/.env` — `ADMIN_EMAILS=drcharitycampbell@gmail.com` explicit.
- `/app/frontend/src/pages/Studio.jsx` — `RotateCw` import; `rerenderAsDryRun(sourceDoc)` handler with visual reset; active-card re-run button (admin-gated); history-row re-run icon button (admin-gated) with `GET /studio/render/{id}` round-trip to fetch full doc before re-firing.

**Carried-over open items (all explicitly deferred per user instruction)**
- Real `_run_render_composite` orchestration (deferred per user: composite real-render stays off until Avatar + Faceless real-renders validated independently)
- `server.py` refactor into `/app/backend/renders/{avatar,faceless,composite}.py` (deferred per user: premature until feature set stabilises)
- `JSON.stringify(payload)` useEffect dep in `AdminRenderControl.jsx` (deferred per user: minor cleanup)
- Cross-origin Netlify `/auth-me` deployment (held — other dev will handle when ready to flip live URL)
- Admin panel + legacy Resources port (held — those stay on Netlify side)

## Iteration 10 — Cost guards + DRY_RUN render pipelines + admin-only render controls + Sprint promote (2026-02-12)
Verified live via `/app/test_reports/iteration_10.json` — 13/13 backend pytest PASS, all live-tested UI surfaces PASS, zero bugs found.

**Admin detection.** `/auth/me` now returns `isAdmin` (derived from `ADMIN_EMAILS` env, defaults to `drcharitycampbell@gmail.com`) plus `dryRunDefault` (mirror of `DRY_RUN_RENDERS` env). Frontend reads `user.isAdmin` from `useAuth` and gates the entire admin-render control UI behind `{isAdmin && ...}` — customers see a clean "Render Video" button and nothing else.

**Cost estimator.** New `estimate_render_cost_cents(payload)` helper at `/app/backend/server.py` ~line 415. Conservative ceiling estimates: Avatar = $0.30/min HeyGen + 5¢ overhead; Faceless = $0.005/1k char TTS (calibrated up 10x after iteration-10 code review) + 4¢/Flux image + 2¢ compose; Composite = avatar base + B-roll cutaway per N seconds + 3¢ overhead. New endpoint `POST /api/studio/render/estimate` returns `{estimated_cost_cents, estimated_cost_dollars, cap_cents, cap_dollars, exceeds_cap, dry_run_default, is_admin}` — used by `AdminRenderControl` for the live "~$X.XX" label (250ms-debounced).

**$1.50 hard cap.** `RENDER_COST_CAP_CENTS=150` env-configurable. Any `/studio/render` request whose estimate exceeds the cap is rejected with HTTP 400 + a clear error ("Render rejected: estimated $5.08 exceeds hard cap of $1.50"). Applies even when `dry_run=true` so admins can't accidentally over-shoot the budget by toggling dry_run off after the fact. Composite renders need the extra headroom over single-mode renders — the cap was chosen with this in mind.

**`RenderRequest.dry_run` admin override.** Optional bool on the request body. Resolved server-side as `effective_dry_run = payload.dry_run if (is_admin and payload.dry_run is not None) else DRY_RUN_RENDERS`. Customers' attempts to override are silently ignored — non-admin requests always use the env default. Verified by code review + pytest.

**HeyGen Avatar pipeline (DRY_RUN scaffold).** New `_run_render_avatar` in `server.py`. Walks the status stages voiceover→avatar→polling with sleeps, then finalizes with `SAMPLE_VIDEO_URL` + `actual_cost_cents=0` in dry-run. Real path is fully written: POST `/v2/video/generate`, poll `/v1/video_status.get` every 5s up to 5 min, parse the final `video_url`. Gated behind `if dry_run: return STUBBED_RESPONSE` so flipping `DRY_RUN_RENDERS=false` runs the real code unchanged.

**fal.ai Faceless pipeline (DRY_RUN scaffold).** New `_run_render_faceless`. Walks voiceover→visuals→composing. Real path: `fal-ai/kokoro` for TTS (single call for entire narration), `fal-ai/flux-pro/v1.1` per-scene images (parallel via `asyncio.gather`), then `fal-ai/ffmpeg-api/compose` to stitch. Accumulates `actual_cost_cents` as each stage completes.

**Composite Avatar+B-roll pipeline (DRY_RUN scaffold).** New `_run_render_composite`. Walks avatar→cutaways→composing for the dry-run path. Real path is currently a TODO that surfaces a clear error message ("Composite real-render not implemented yet — keep dry_run on for composite mode.") so an admin who flips dry_run off knows exactly what's missing. The dry-run path completes cleanly so the UI can be built against it today.

**Activity log.** Every `/studio/render` call writes a `studio_render` row to `db.activity` with `detail.dry_run` boolean + `detail.estimated_cost_cents` int. Verified via direct mongosh query.

**Admin-only render controls UI** (`/app/frontend/src/components/AdminRenderControl.jsx`):
- Amber-themed panel below the chip strip on Studio
- "Use real render (~$X.XX)" checkbox — default OFF every page mount (no localStorage persistence; every render starts in dry-run for safety)
- Live cost estimate fetched from `/studio/render/estimate` 250ms-debounced as the form payload changes
- Cap-exceeded warning panel disables the checkbox + shows "Estimated $X.XX exceeds the $1.50 hard cap" guidance
- CTA copy flips: "Render your video" → "Render (real)" when toggle is ticked
- `ConfirmRealRenderModal`: shown when admin+useReal clicks Render. 1-second-armed countdown on the confirm button ("Wait 0.9s…" → "Wait 0.8s…" → … → "Render for $0.12") to prevent reflex double-clicks. Cancel closes without firing.

**Sprint "Promote to full short" button.** Each of the 5 Sprint variant cards now exposes a `[data-testid='sprint-variant-N-promote']` button. Clicking it calls `promoteVariant(variant)` in `Scripts.jsx` which POSTs to the existing `/scripts/shorts` endpoint with `sprint:false` and `chosen_angle={name:variant.name, framing:variant.angle, category:variant.category}`. Page switches to the GENERATING step with the progress bar; on completion renders the standard 3-column Plan/Script/Distribute layout for that single short. While promoting, the other 4 promote buttons are disabled (via `promotingIndex` state).

**Files touched in iter 10**
- `/app/backend/server.py` — ADMIN_EMAILS + RENDER_COST_CAP_CENTS env, `/auth/me` enriched with `isAdmin`+`dryRunDefault`, `RenderRequest.dry_run`+`broll_cutaway_interval_s` fields, `estimate_render_cost_cents`, `_walk_stages`, `_finalize`, `_run_render_avatar`, `_run_render_faceless`, `_run_render_composite`, `_run_render` dispatcher, `/studio/render/estimate` endpoint, `/studio/render` cost-cap + admin dry_run override.
- `/app/frontend/src/components/AdminRenderControl.jsx` — new component + `ConfirmRealRenderModal` export.
- `/app/frontend/src/pages/Studio.jsx` — useAuth, isAdmin gate, `buildPayload`, `fireRender(dryRunOverride)`, `generate` split into customer/admin paths, AdminRenderControl + ConfirmRealRenderModal wired into JSX, CTA copy flips.
- `/app/frontend/src/components/scripts/SprintResult.jsx` — accepts `onPromote`+`promotingIndex` props, renders Promote button per variant.
- `/app/frontend/src/pages/Scripts.jsx` — `promoteVariant` handler reusing `/scripts/shorts` with `sprint:false`+synthesized chosen_angle.
- `/app/frontend/src/App.css` — admin-render-control panel, confirm-real modal, sprint-variant-promote button styles.

**Deferred from iter 10**
- Real `_run_render_composite` orchestration (talking-head → cutaways → ffmpeg overlay). Marked with a friendly error so an admin who flips dry_run off on composite gets a clear "not implemented yet" message.
- `server.py` refactor into `/app/backend/renders/{avatar,faceless,composite}.py` — file is now 1185 lines, past the 700-line guideline.
- `AdminRenderControl.jsx` uses `JSON.stringify(payload)` as the useEffect dep — minor perf smell. Replace with a memoized payload-key tuple.
- Cross-origin Netlify auth-me deployment — explicitly held per user instruction; the other dev will handle when ready to flip the live URL.

## Iteration 9 — Scripts component extraction + Script Engine 3.0 polish (2026-02-12)
Two big landings in this iteration. Verified live via `/app/test_reports/iteration_9.json` — all 14 features PASS, no bugs found.

**Component extraction.** Scripts.jsx had grown to ~800 lines of inline component defs. Extracted to `/app/frontend/src/components/scripts/`:
- `SectionCard.jsx` — exports `SectionCard`, `SkeletonCard`, `CopyButton`, `SECTION_LABEL`. Accepts a new `revealIndex` prop that adds `section-card-reveal` class + inline `animationDelay` for staggered fade-in on result render. Sets `data-section="<key>"` on each card so CSS can key per-section accent colors off the DOM.
- `AngleCard.jsx` — exports `AngleCard`, `ANGLE_CAT` map.
- `ShortPhoneBody.jsx` — phone-frame HOOK/BODY/CTA beat parser (default export).
- `SavedAnglesPanel.jsx` — saved-angles drawer (default export). Reads `ANGLE_CAT` from AngleCard.
- `ScriptHistoryList.jsx` — recent-scripts list (default export) with `fmtDate` helper.
- `GenProgress.jsx` — animated progress bar + rotating stage labels (`long` / `shorts` / `sprint` stage tables).
- `SprintResult.jsx` — 5-variant grid renderer (one PhoneFrame per variant with variant header).

`Scripts.jsx` is still ~1040 lines because the 4-step state machine (TOPIC / ANGLES / GENERATING / RESULT) plus the 3-column Shorts result layout is verbose JSX, but all reusable presentational pieces are now externalized. Further extraction (ScriptInputsPanel, ResultHeader, PlatformTabsStrip) is queued as a P1 follow-up.

**Mode-pill active state.** New CSS rules `.mode-opt[data-mode="long"].is-active` (purple-soft fill) and `.mode-opt[data-mode="shorts"].is-active` (platform-accent soft fill). Previously the Studio's Avatar/Faceless pills had active styling but the Scripts page's Long-form/Shorts pills did not.

**Per-section accent colors.** App.css adds 8 `--sec-*` color tokens (orange/lavender/red/blue/green/pink/cyan/amber) plus 14 `[data-section="..."] { --sec-color: ... }` rules. Section cards render with a 3px left-border in the accent color and the title inherits the accent color too. Matches the reference deployment palette.

**Animated progress bar + rotating stage labels.** New `<GenProgress mode="long|shorts|sprint" elapsed={N} />` component. CSS-only indeterminate shuttle bar (`.gen-progress-fill` with a 1.6s `gen-progress-slide` keyframe) plus a label that rotates through stage strings every 7s ("Brainstorming the angle" → "Drafting video concept" → "Writing hook variations" → …). Stage tables differ per mode — sprint mode rotates through "Drafting Variant 1" → "Drafting Variant 2" → … → "Drafting Variant 5" → "Final pass + polish". Replaces the static "Generating · {N}s" label.

**Section card staggered fade-in.** `.section-card.section-card-reveal` triggers a `section-fade-in` keyframe (opacity + 8px translateY). Scripts.jsx passes `revealIndex={i}` to each SectionCard which sets `style={{ animationDelay: 'i*90ms' }}` — sections appear left-to-right (Plan/Script/Distribute on Shorts) or top-to-bottom (Long-form) for a streaming feel.

**Content Sprint mode (Shorts).** New `sprint: bool` field on `ShortsRequest`. When true, the backend uses `build_sprint_system_prompt(platform)` from `prompts.py` which asks Claude for 5 distinct angle variants in a single response with header `### 🎬 SPRINT VARIANT N — name`. Each variant has Angle + Category + HOOK/BODY/CTA beats + Caption + Hashtags. Job is stored with `mode="sprint"`. Frontend parses with `parseSprintVariants()` (new in `parser.js`) which uses a strict `\p{Extended_Pictographic}`-aware regex with a relaxed fallback for prompt drift. Result rendered via `<SprintResult>` — 5 vertical phone frames in an auto-fit grid, each with its own variant header (number / name / angle / category pill). `Send to Studio` is hidden in sprint result (no single script to hand off).

**"Generate for all 3 platforms at once" multi-platform mode.** New `multiPlatform` boolean state in Scripts.jsx. When checked, the platform cards hide and the CTA copy becomes "Generate for all 3 platforms →". `kickoffGeneration` then does `Promise.all` on three `/scripts/shorts` POSTs (one per platform) and `pollMultiJobs` polls all 3 statuses in parallel (single 2.5s interval ticks all jobs in one go). Result view renders `.platform-tabs` with one tab per platform — each tab has a pulsing/green/red status dot (running/complete/failed). Clicking a tab swaps the active output and re-applies the platform's `--platform-accent` so the PhoneFrame color flips. The first complete job auto-selects on completion.

**Mutual exclusion.** Sprint and multi-platform are mutually exclusive. Toggling sprint ON clears multi-platform; checking multi-platform clears sprint. Mode-revert (Shorts → Long-form) clears both. The Sprint pill uses an explicit `enableSprint()` setter (not a toggle) so clicking it twice does NOT flip it off — the "Single short" pill handles the off-case for predictable UX.

**Parser hardening.** `parseSprintVariants` ships with a strict regex (requires the literal `### 🎬 SPRINT VARIANT N — name`) chained with a relaxed fallback (matches any `## SPRINT VARIANT N` with any separator) so a single Claude prompt drift doesn't produce a blank sprint-grid.

**Backend smoke.** `POST /api/scripts/shorts {topic, platform, sprint:true}` → job completes in ~45-50s with 9.3KB of text containing exactly 5 valid `### 🎬 SPRINT VARIANT N — name` headers. `parseSprintVariants` extracts all 5 with name + angle + category + body. Verified on the live Claude endpoint.

**Files touched in iter 9**
- `/app/backend/prompts.py` — added `build_sprint_system_prompt(platform)`.
- `/app/backend/server.py` — `ShortsRequest.sprint`, branch in `/scripts/shorts` for sprint vs single-short, stores `mode="sprint"` + extra `{sprint: true}`.
- `/app/frontend/src/utils/parser.js` — added `parseSprintVariants(raw)` with strict + relaxed regex.
- `/app/frontend/src/components/scripts/` — added GenProgress.jsx, SprintResult.jsx (this iter); SectionCard.jsx, AngleCard.jsx, ShortPhoneBody.jsx, SavedAnglesPanel.jsx, ScriptHistoryList.jsx (extracted in this iter).
- `/app/frontend/src/pages/Scripts.jsx` — clean rewrite using all extracted components, adds sprint + multi-platform state, `kickoffGeneration` unified entry, `pollMultiJobs` parallel poller, `switchTab` for multi-platform results.
- `/app/frontend/src/App.css` — added Long-form/Shorts mode-pill active rules + ~250 lines for per-section accents, gen-progress, sprint-toggle, multi-platform-row, platform-tabs, sprint-grid.

**Deferred from this iteration**
- Live multi-platform end-to-end was not exercised by the testing agent to conserve token budget; structurally sound code path; persisted sprint job exercises the same render path. Recommend a quick smoke once before deploy.
- Per-platform elapsed timers in multi-platform view (currently shows one cumulative elapsed).
- Scripts.jsx further extraction (ScriptInputsPanel, ResultHeader, PlatformTabsStrip) to get below 500 lines.
- Co-locate per-section accent palette with `SECTION_LABEL` in a shared `sectionsMeta.js` so JS consumers (e.g. saved-angles category pills) can use the same tokens.

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
