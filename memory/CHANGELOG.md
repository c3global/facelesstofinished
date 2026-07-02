# Faceless to Finished — What's New

A running log of every customer-visible change shipped to the app. Most recent
first. Plain English — if you're a customer reading this, this is for you.

> Want internal product-spec depth? See `PRD.md` (internal-only — that's where
> admin tooling, webhooks, backend plumbing, and migration scaffolding lives).

> **For developers / agents working on this app**: this file plus
> `/app/frontend/src/changelog.js` MUST be updated on every deploy. The footer
> popup in the app reads from `changelog.js`. See PRD.md for the workflow rule.

---

- **Studio Founder Lifetime = auto-Founder.** Charity clarified her $297 (or 3×$99 payment plan) Studio Founder Lifetime product is meant to be truly unlimited from the moment Pinball fires. The webhook was setting `studio_lifetime: True` on the buyer but NOT `founders: True`, and the render quota gate ONLY checks `founders`. Fixed by stamping `founders: True` alongside the existing `studio_lifetime` metadata whenever `product == "studio"` in the Pinball webhook. Same fix updates the GHL outbound push so Studio purchases correctly tag as `founder` in her workflows (was tagged as `pro` before). Production DB is unaffected — existing Studio Founder buyers already have the flag set manually; this change ONLY affects NEW purchases going forward. The comment on the old `founder=False` GHL push line was corrected (previous engineer's assumption that "founders never enter via Pinball" was wrong — that IS how she sells Founder). Payment plan (3×$99) is the same Pinball product_id as the $297 one-time, so single mapping covers both.

## v1.19.0 — July 2, 2026 (Passwordless magic-link sign-in + tier cleanup)

- **Passwordless sign-in** — the login screen now emails you a secure
  one-time link instead of trusting whoever types your address. Links
  expire in 15 minutes and can only be used once. Closes the security
  hole where anyone who knew your email could impersonate you.
- **Delivery via Resend** (primary) with the existing GoHighLevel
  outbound webhook as automatic fallback so a Resend outage never
  locks a customer out.
- **Tier names cleaned up** — Starter ($49) / Pro ($179) / Pro Plus
  ($349) / Founder. The internal "Creator" name that never matched a
  real product SKU was retired. AppSumo Tier 1/2/3 now map 1:1 to
  internal t1/t2/t3, no more mental gymnastics.
- **Founder tier is unchanged** — direct-sale customers (Studio
  Founder $297 one-time or 3×$99 payment plan) and the original
  grandfathered founders keep unlimited access. No quotas, no
  changes to your account.
- **AppSumo Licensing v2 fully wired** — real webhook + OAuth
  redemption flow, HMAC signature verification, license-key
  redemption on top of the pre-uploaded code inventory. Numeric
  tiers (1/2/3) from AppSumo now resolve correctly to internal ids
  and stamp entitlements at redemption so you can sign in
  immediately after purchase.

---

## v1.18.4 — July 1, 2026 (Nano Banana for scene stills + Sora 2 test lane)

- **Scene stills upgraded to Gemini Nano Banana.** Faceless mode scenes
  now generate via Gemini Nano Banana instead of Flux 1.1 Pro. Higher
  photorealistic quality for professional aesthetic, and generation
  cost comes off your Emergent Universal Key balance instead of fal.ai
  per-call billing.
- **Flux stays as a silent fallback.** If Nano Banana ever rate-limits
  or hiccups, the pipeline transparently falls back to Flux so renders
  don't crash mid-pipeline. Cache prefix updated so we don't
  accidentally serve old Flux outputs.
- **&ldquo;AI&rdquo; source pill relabeled to &ldquo;AI Still&rdquo;.**
  Sets the right expectation — this is a professional-quality
  photograph, not motion video. Motion is coming as a separate premium
  lane once Sora 2 quality is validated.
- **Admin-only Sora 2 test endpoint.** Charity can now fire test
  cinematic clips at `/api/admin/studio/test-sora2` to evaluate quality
  and cost per render before deciding whether Sora 2 becomes the
  "Cinematic Faceless" engine or motion stays parked behind BYOK.
- **Roadmap Faceless mode blurb updated** to reflect the stock-first
  + Nano Banana workflow.

---

## v1.18.3 — June 30, 2026 (HeyGen 5,000-char limit friendly error)

- **Fixed:** Avatar Mode renders were failing at 45% with a wall of raw
  HeyGen JSON (`{"error":{"code":"invalid_parameter","message":"String
  should have at most 5000 characters"...}}`). Root cause: HeyGen's
  API caps script text at exactly 5,000 characters on both v3 and v2.
  Long-form scripts routinely exceed this.
- Two guards added:
  1. **Client-side pre-flight:** Studio now rejects too-long scripts
     BEFORE hitting the backend, so you get an immediate friendly hint
     ("Your script is 8,214 characters, but Avatar mode maxes out at
     5,000") instead of waiting 30 seconds to see a red error at 45%.
  2. **Backend friendly mapping:** if a job somehow still hits HeyGen
     with a too-long script, the failed-render card now translates the
     raw HeyGen JSON into plain English.
- Both messages recommend switching to Faceless mode, which has no
  character limit (voiceover is chunked scene-by-scene by Kokoro TTS).

---

## v1.18.2 — June 30, 2026 (Audience-neutral roadmap + cleaner header)

- The public nav (Roadmap · Changelog · Sign in) now sits on the same
  row as the logo and the theme toggle, instead of below the hero
  image. One clean header row, no awkward duplicate links.
- The Sign-in button is automatically hidden when you&rsquo;re already
  on the login page (no point linking to the page you&rsquo;re on).
- The footer now renders on the login page too — so the version pill
  + "What&rsquo;s New" amber dot are visible from your very first
  visit, not just after you sign in.
- The roadmap copy is now audience-neutral. It used to lead with
  "AppSumo buyers" — but this product is for every customer, not
  just one launch partner. Founders, lifetime-deal holders, and
  everyone who joins us later all see the same forward-looking page.
- Renamed Shipped &ldquo;Redemption flow&rdquo; and In Progress
  &ldquo;Production launch&rdquo; for the same reason.

---

## v1.18.1 — June 30, 2026 (P0 bug fix + admin-editable roadmap)

- **Fixed (P0):** The "Make thumbnail" handoff was truncating the cover
  concept prompt to just the `[matches "..."]` label (~57 chars) instead
  of passing the full 500-700 char prompt body. The parser was using a
  single-line regex while Claude's current template puts the prompt
  body on the lines BELOW the label. Now the parser splits the section
  into numbered entries first, then captures each entry's full
  multi-line body. Backwards compatible with the legacy single-line
  format.
- **Admin can edit the Roadmap inline.** Pencil + trash + reorder
  arrows appear on every card when you're signed in as
  drcharitycampbell@gmail.com. "+ Add item" button at the bottom of
  each column. Every save goes to a Mongo-backed `roadmap_items`
  collection — survives redeploys, can be backed up. Buyers see the
  read-only version exactly as before.
- **Roadmap content expansion:** added 4 new items to Planned (Script
  Revision Tools as TOP REQUEST, Brand Voice Profiles, Authority
  Content Templates, Content Series Builder) + 3 to Considering
  (Approval Workflow, Multilingual Scripts, Agency / White-label).
- **Positioning subhead** on the roadmap: *"The AI studio for
  off-camera authority content — built for consultants, coaches,
  experts, and speakers who need a video presence without being on
  camera every day."*
- **Landing-page nav** (top-right of /login): Roadmap · Changelog ·
  Sign in. Reviewers can browse before signing up.
- **New public /changelog page** — timeline view of every shipped
  version, reads from the same source as the in-app footer popup.
- **Release banner** on Scripts page pointing to the roadmap.
  Dismisses per version: bump APP_VERSION and every buyer sees one
  fresh banner.

---

## v1.18.0 — June 30, 2026 (Public Roadmap page)

- **New `/roadmap` page** linked from the footer. No login required —
  AppSumo reviewers, prospective buyers, and anyone curious can see
  exactly what's shipped, what we're building right now, what's coming
  next, and what we're considering.
- **4 columns:** Shipped (8 items including Script Engine, Studio
  Avatar + Faceless, Thumbnail Engine, BYOK, AppSumo redemption flow,
  Admin Dashboard, Light/Dark themes), In Progress (Production deploy +
  AppSumo launch, GoHighLevel sync), Planned (Canva integration ←
  TOP REQUEST, Cinematic Faceless, Upload B-roll, Record voiceover,
  Brand kits, Bulk CSV → video, AI music, Native publishing, Analytics),
  Considering (Voice cloning, Team seats, Webhook/Zapier, Avatar BG
  removal, Mobile app).
- Tone is founder-honest: every blurb describes the *benefit* to the
  buyer, not the underlying tech. We update this page in the same
  change as the code itself — no stale promises.
- Both dark + light themes polished to the v1.17.0 standard.

---

## v1.17.0 — June 30, 2026 (Light-mode polish round 2)

- **Hero eyebrow** ("FACELESS TO FINISHED · VIDEO ENGINE" /
  "THUMBNAIL ENGINE · V1") was 11px copper on lavender — barely
  readable. Now uses `color-mix(in srgb, var(--warning) 78%, #000 22%)`
  for a deep copper with `font-weight: 700` and slightly tighter tracking
  in light mode. Studio's mode-specific overrides (avatar/faceless) get
  the same deeper-copper treatment.
- **"Owner · unlimited renders" pill** (`.quota-pill-unlimited`) had a
  16%-opacity gradient that completely washed out on light bg. Now uses
  an 18%/14% warm-gradient on white surface with a full-saturation copper
  border and `color-mix(in srgb, var(--warning) 75%, var(--text))` text.
  Crown icon picks up the warning token. Same fix applies to
  `.thumb-quota-unlimited` on the Thumbnails page.
- **Settings/Keys page** — every dark-gray surface flagged by the iter_40
  testing agent now has a `[data-theme="light"]` override:
  - `.settings-keys-hero` → soft accent+warning gradient on white
  - `.settings-key-card` → pure white surface with design-token border
  - `.settings-key-card.is-saved` → warm cream wash for saved state
  - `.settings-key-input` → light bg with focus-ring
  - `.settings-key-save-btn` → copper CTA (warning token)
  - `.settings-key-delete-btn` → soft danger
  - All text colors route through `--text` / `--muted` / `--warning`.
- **Dark mode unchanged** — every override scoped to `[data-theme="light"]`
  cascade.

---

## v1.16.0 — June 30, 2026 (Thumbnails light-mode polish)

- **Thumbnails page in light mode** no longer renders as dark-gray boxes
  on a pale background. Form card, prompt textarea, optional script-topic
  input, Engine/Aspect segmented chips, gallery tiles, tile overlay icons,
  zoom hint, and engine pills all gain dedicated `[data-theme="light"]`
  overrides that route through the design tokens (`--surface`, `--bg`,
  `--border`, `--text`, `--muted`, `--accent`, `--warning`).
- **Active states** for Engine + Aspect now use a soft warm gradient
  (warning + accent mix at 14%) with a copper border so the selection is
  unmistakable.
- **Generate thumbnail CTA** in light mode uses the copper warning token
  so the primary action pops against the pale surface.
- **Tile prompt + meta text** uses the muted token (`rgb(91, 86, 128)`) so
  copy reads crisply on white backgrounds (was light lavender before —
  invisible against the pale page).
- **Dark mode is untouched.** All overrides are scoped to
  `[data-theme="light"]` — verified in regression: `.thumb-card` bg in
  dark stays `rgba(15, 10, 30, 0.55)` exactly.

---

## v1.15.0 — June 30, 2026 (refactor + cross-origin auth)

- **Cross-origin auth-me fixed.** The CORS middleware was configured with
  `allow_origins=["*"]` + `allow_credentials=True` — invalid per W3C spec,
  browsers silently reject the combination on cross-origin `/auth/me` calls
  from the deployed frontend. Now uses either a whitelist via
  `FRONTEND_ORIGINS` env var or a permissive regex match (still safe — the
  auth boundary is the JWT bearer token, not the origin).
- **server.py refactor pass 1.** Caption burn-in pipeline extracted to a
  dedicated `backend/caption_burn_in.py` module. server.py shrinks by ~100
  lines. The 7-test pytest regression suite (`test_caption_burn_in.py`) is
  unchanged — locks the contract through the extraction.
- **Scripts.jsx refactor pass 1.** Constants (`MODES`, `STEPS`, `LENGTHS`,
  `PLATFORMS`, `TAGLINES`, `LONG_PHASES`, `SHORTS_PHASES`, `SPRINT_PHASES`,
  `angleKey`, `currentStreamingPhase`) extracted to
  `components/scripts/scriptsConstants.js`. The platform-accent
  side-effect (mirrors active platform onto `documentElement[data-platform]`)
  extracted to `hooks/usePlatformAccent.js`. Scripts.jsx shrinks by ~80
  lines. No behavioural change — same data-testids, same renders.

---

## v1.14.0 — June 30, 2026

- **Cloudflare 502 → warm message.** When the render server is briefly
  unavailable (deploy, restart), the UI now says "Our render server is
  warming back up — give it ~30 seconds and try again, your prompt is
  preserved" instead of the cryptic Cloudflare default. Network errors
  get a separate "couldn't reach the server" message. Applies to
  `friendlyError()` in the Thumbnails page (rewriter + generator +
  concepts).
- **Render regen soft-cap (5 per script).** Studio's `regenerate()`
  tracks regen count per `(mode, script)` tuple in localStorage. After 5,
  further clicks show "Try tweaking the script or avatar choice instead —
  fresh inputs render better than another retry." Owners (DEV_BYPASS,
  studio grants) and Founders are exempt.
- **Light mode polish:**
  - Footer "Have a redemption code?" link rewired to use the design-token
    `--muted` color so it tracks themes (was hardcoded lavender,
    disappeared against the pale-purple light bg).
  - `--surface-hover` in light theme bumped 5%→9% so card hover states
    are visible (the previous 5% was identical to resting state).
  - TikTok platform card (#25F4EE cyan): foreground swapped to near-black
    via a new `--platform-fg` variable. Reels/YouTube unchanged (already
    high contrast on white text).
- **Caption burn-in regression suite** added at
  `backend/tests/test_caption_burn_in.py` — 7 tests verify
  `_burn_in_captions` exists, soft-fails cleanly without a fal.ai key /
  without a video_url / on fal.ai outages, and that the style/position
  preset maps remain intact. Locks the contract so a future server.py
  refactor can't silently disable subtitle burn-in.

---

## v1.13.0 — June 30, 2026

- **GoHighLevel integration** ships. Every new buyer (Pinball webhook) and
  every AppSumo code redemption now pushes a tagged contact JSON to your
  GHL workspace automatically. Payload is stable + flat:
  `{email, tier_id, tier_label, source, tags, metadata, occurred_at, app}`.
  Tags include `f2f48-customer`, `tier:<id>`, `source:<pinball_purchase |
  appsumo_redemption>`, plus `founder` for the 39.
- **Admin Buyers tab** gains: a `GHL: connected | off` pill in the toolbar,
  a `Test GHL` button that sends a sentinel payload without touching any
  buyer record, and a per-row "Push to GHL" replay button for buyers who
  landed via a legacy path or during a transient outage.
- **Failures are observable**: every failed GHL push lands in
  `db.activity` as `ghl_push_failed` with the offending payload + HTTP
  status / exception, ready for replay.
- **Config**: set `GHL_WEBHOOK_URL` in `backend/.env` (paste the inbound
  webhook URL from your GHL workflow trigger node). Optional shared-secret
  header via `GHL_WEBHOOK_AUTH_HEADER="Header-Name: value"`.

---

## v1.12.0 — June 30, 2026

- **NEW: API Keys settings page** for Pro Plus + Founder members — plug in
  your own **Anthropic**, OpenAI, **Google AI Studio**, **ElevenLabs**,
  HeyGen, and fal.ai keys and your scripts, thumbnails, and video renders
  draw from your own provider quotas instead of ours.
- **Anthropic key** unlocks the Script Engine + thumbnail prompt rewriter on
  your own Claude quota — every script generation routes through your key
  when one is saved.
- Keys are **encrypted at rest** (Fernet symmetric AES-128 + HMAC) and never
  displayed back to the dashboard after save — you only see a safe preview
  like `sk-…0abc`.
- **Thumbnails — click any image in your gallery** to open a full-screen
  preview with Download + Copy prompt actions right there (no more right-
  clicking to save).
- **Admin Usage tab** now tracks thumbnails alongside scripts and renders:
  new sortable Thumbnails column, Premium/Fast split in the per-buyer
  drilldown, footer totals, CSV export columns, and a new "Thumbnails
  generated" tile on the Stats tab.
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
