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

## Iteration 4 — Async job pattern (2026-01-12)
- ✅ Fixed Cloudflare 60s edge timeout for long-form script generation. `/api/scripts/long`, `/scripts/shorts`, `/scripts/repurpose` now follow the same async-job pattern as `/api/studio/render`:
  - POST inserts a mongo record with `status="running"` and spawns the Claude call in `asyncio.create_task`
  - Returns the queued record in <1s (no edge-timeout exposure)
  - Frontend polls `GET /api/scripts/job/{id}` every 2.5s with an elapsed-seconds counter UI
- ✅ Tested end-to-end on the PUBLIC preview URL — 18/18 backend, 100% frontend per `/app/test_reports/iteration_4.json`

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
