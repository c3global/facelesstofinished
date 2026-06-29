# Faceless to Finished — What's New

A running log of every change shipped to the app. Most recent first. Plain English,
no technical jargon — if you're a customer, this is for you.

> Want the in-depth product spec instead? See `PRD.md` (internal).

---

## June 29, 2026 — Resource Library restored + Faceless render reliability fix

**Resource Library is back.** The 5 production guides (Pitch Perfect AI Voiceover
Guide, B-Roll Prompt Bank, Thumbnail Kit, Production Map, Publishing Checklist)
are now accessible again from the new **Resources** tab in the header. The PDFs
themselves were never lost — they just weren't linked from the new dashboard after
the platform migration.

**Faceless renders no longer fail with "client has been closed."** A backend bug
was causing long Faceless videos (1000+ characters, 6+ scenes) to fail at the
voiceover step with a confusing error message. Real video renders now complete
end-to-end again, even for long scripts.

---

## February 23, 2026 — Multi-platform comparison view + Shorts result polish

**New: Compare-all multi-platform view.** When you generate the same short for
YouTube + Instagram Reels + TikTok at once, you can now click **"Compare all"**
to see all three side-by-side instead of flipping between tabs. Each phone
displays in its platform's signature color (red for YouTube, fuchsia for Reels,
teal for TikTok) so you can A/B test which one wins at a glance.

**New: Per-platform "Send to Studio" buttons.** In the compare-all view, each
phone now has its own Send-to-Studio button so you can one-click pick your winning
platform after comparing.

**New: "New short" sticky button on the result page.** Once you're viewing a
result, an amber button in the top toolbar lets you start a fresh generation
without flipping to Long-form and back to Shorts.

**Improved: Recent scripts list now filters by mode.** When you're on the Shorts
tab, "Recent scripts" only shows shorts and sprints (not long-form). A pill row
above the list lets you switch between **Current / All / Long / Shorts / Sprint**
filters whenever you want a different view.

**Improved: Phone rim color now matches the script's platform.** Loading a Reels
short from history now shows the fuchsia rim; TikTok shows teal; YouTube stays
red. Previously every history-loaded short kept whatever rim you last picked.

**Improved: YouTube cell in compare-all now renders ON-SCREEN / B-ROLL chips
correctly.** Was previously showing them as raw bracketed text on the YouTube
column while Reels and TikTok rendered them as chips.

**Improved: TikTok TEXT chips are now readable.** The dark teal accent now uses
black ink instead of white, so chips are legible on TikTok's bright teal palette.

**Improved: Production Notes + Cover Image Prompts now align side-by-side at equal
width on the result page.** Previously, Production Notes was twice as wide and
looked unbalanced next to the narrow Cover Image Prompts card.

**Improved: Section card colors rebalanced.** Adjacent cards no longer share
similar hues — B-Roll Shot List is now green (matches the inline B-ROLL chip),
On-Screen Text is now cyan (was duplicate purple with Hashtags), Cover Image
Prompts is now bright orange (was near-clone of the warm amber Title card).

---

## February 19, 2026 — Faster renders + smarter B-roll + voice favorites

**Faster Faceless renders.** The voiceover step now runs in parallel with image
generation instead of one after the other. Typical wall-clock savings: 10-15
seconds per Faceless render.

**Smarter B-roll selection.** Stock footage searches now strip cinematic vocabulary
(words like "wide", "overhead", "drift", "soft") that were confusing Pexels'
keyword-tag search. The full cinematic prompt is still used for AI-generated
visuals — only stock searches get the streamlined query. Result: stock B-roll now
actually matches what your script is about.

**Better stock resolution.** Stock footage floor bumped to 720p, ceiling to 1080p
(was a mix of 480p-4K). No more soft 480p clips on modern screens, no 4K wasting
render time.

**New: Favorite voices.** Star any HeyGen voice in the voice picker — favorites
get pinned to the top of every tab. There's also a dedicated ★ tab to see just
your favorites. Works across the 2,329-voice catalog so you don't have to
scroll-search every time.

**New: Favorite avatars.** Same star-toggle pattern for the 1,281-avatar HeyGen
catalog. Star, switch to the ★ tab, done.

**New: Voice picker now has a "Neutral" tab.** Recovers 76 voices that HeyGen
returns with gender="unknown" (kid voices, custom uploads, specialty voices).
They were previously hidden behind All-only.

**Fixed: Custom voice uploads now visible.** Custom uploaded voices (Dr. CK
Casual, Course Voiceover, etc.) now show up correctly in the picker.

**Fixed: Avatar picker no longer stuck loading.** A 30-second backend timeout was
killing the avatar list before HeyGen could return all 1,281 records. Timeout
bumped to 90s; subsequent loads serve instantly from cache.

**Improved: Hook variations rendering.** Hook lists now render cleanly without
spurious blank lines between numbered items.

**Improved: Copy Script now preserves formatting.** Pasting into Google Docs,
Notion, or Word now keeps the green B-roll cues, amber scene headers, and bold
emphasis. Previously formatting was stripped on paste.

**New: Drip / progressive script rendering.** The Script Engine now streams
Claude's output as it's being generated instead of waiting for the full response.
You see the script forming live, with a status banner showing the current phase
("Drafting video concept…", "Writing hook variations…", etc.).

**New: Long-form toggles.** Three toggle switches on the long-form mode let you
choose whether to include Hook Variations, B-Roll Shot List, and Production Notes
in your output. Default ON.

---

## February 19, 2026 — Login page polish + better first-time experience

**New: Landing-style login page.** First-time visitors now see a brief intro of
what Faceless to Finished is (Script Engine, Avatar Studio, Faceless Render)
alongside the sign-in card, instead of a bare "Welcome back" prompt that assumed
prior context.

**Improved: Login copy adapts.** First-time visitors see "Sign in." Returning
customers see "Welcome back." The transition is automatic.

**Improved: Login hero image.** New 4-device product mockup (iMac + iPad + iPhone
+ MacBook) with a subtle layered purple/amber glow behind it.

**Improved: Light mode readability.** The cream-to-amber "10× faster" gradient
now uses a deeper amber-bronze gradient in light mode so the headline reads
cleanly on near-white backgrounds.

---

## February 19, 2026 — Critical sign-in + webhook fixes

**Fixed: Admin-granted buyers can sign in.** Customers who were granted access
through the Admin → Buyers UI but couldn't sign in (kept getting "Could not sign
in. Use the email you bought with.") can now access the app correctly.

**Fixed: Pinball webhook now accepts the real Pinball payload format.** Live
Pinball/GoHighLevel workflows were returning 400 errors because the webhook was
too strict about payload shape. The receiver now handles 6 different email paths
and 4 different items paths — matching what Pinball actually sends.

**New: One-shot welcome toast on first sign-in after purchase.** Customers who
just completed a Pinball checkout see a "Welcome — Base + Shorts access unlocked"
toast the first time they sign in. Shows once, then disappears.

---

## February 19, 2026 — Shorts result layout: Bento grid

**Improved: Shorts result page redesigned.** The lopsided 3-column layout
(Plan / Phone / Distribute) was replaced with a clean bento grid:

- The phone preview is now anchored at the top center as the visual focus.
- All 8 auxiliary cards (Hook Variations, Caption, B-Roll, Hashtags, On-Screen
  Text, Title/Thumbnail Variants, Cover Image Prompts, Production Notes) sit
  in a responsive 3-column grid below the phone.
- The top row pins Hook Variations + Caption + B-Roll Shot List — the cards
  most users copy-paste first.

---

## February 18, 2026 — Native Admin Panel + Pinball webhook + Netlify import

**New: Admin Panel (`/admin`).** A native admin dashboard inside the app, gated
by admin email. Three tabs:

- **Buyers**: search, filter by entitlement, grant or revoke access, bulk
  delete, optimistic UI.
- **Activity**: full event log with type/email/date filters, replay button for
  any failed webhooks, JSON detail expand.
- **Stats**: signups chart, revenue, total renders, scripts, active users,
  entitlement breakdown.

**New: Pinball webhook receiver.** Live `POST /api/pinball/order-completed`
endpoint that auto-provisions buyers on every paid order. Multiple product IDs
map to multiple entitlements. Failed events log to Activity for replay.

**New: Netlify Buyer Import.** Bulk-imports buyers from the legacy Netlify
backend. Existing records merge intelligently (entitlements union, counters
max(), no null overwrites).

**New: CSV Import for Buyers.** Drop a CSV file with at least an `email` column
and the admin tab will batch-create buyer records. Flexible column aliases.

**New: Activity log management.** Multi-select rows, bulk delete, single-row
delete, and a "Wipe all" button with confirmation. Wipes themselves are logged
so you always know who cleared the audit trail.

**New: Auto-refresh on Buyers + Activity tabs.** The admin tabs now silently
re-poll every 20 seconds so webhook events surface within seconds of arriving.

---

## January 12, 2026 — Script Engine 2.0: Two-step gated flow + sprint mode

**New: Two-step generation flow.** The Script Engine now first returns 4
distinct creative angles for your topic (each tagged Curiosity / Contrarian /
How-To / Story / List). You pick one, then commit to the full script. Much
better targeting than the old single-shot generation.

**New: Sprint mode.** Generate 5 variants of the same short at once — perfect
for A/B testing different hooks on the same idea.

**New: Saved angles.** Bookmark any angle you generated and recall it later.

**New: "Cut into a Short" repurposing.** Take any long-form script and have
Claude rewrite it as a Shorts script.

**New: "Send to Studio" handoff.** Generated scripts can be one-click-pushed
into Studio with the narration and B-roll prompts pre-filled.

**New: Multi-platform Shorts.** Generate the same short tailored for YouTube
Shorts, Instagram Reels, AND TikTok in a single click — each platform-tuned
(YouTube emphasises retention hooks, Reels emphasises shareability, TikTok
emphasises the algorithm-friendly first 3 seconds).

---

## January 12, 2026 — Studio launch

**New: Studio mode for video rendering.** Two pipelines:

- **Avatar**: HeyGen avatar talking head + voiceover from 2,329 HeyGen voices.
  1,281 avatars to choose from. Pick aspect ratio, captions, and you're done.
- **Faceless**: AI voiceover + auto-generated B-roll (stock footage from Pexels
  / Pixabay, or AI-generated visuals via Flux + Kling 2.1).

**New: 6 picker modals.** Avatar, Voice (HeyGen), TTS Voice (Kokoro), B-Roll
Source, Aspect, Captions — each a contained modal with tabs, search, and
scrolling.

**New: Captions auto-flip.** Captions default ON for 9:16 (Shorts/Reels) and
OFF for 16:9 (long-form). Sticky once you override.

**New: Auto scene generation.** Faceless mode reads your script paragraphs and
auto-suggests one B-roll scene per paragraph. Up to 12 scenes; you can add,
remove, edit, or reorder.

**New: Per-scene source override.** Pick AI / Pexels / Pixabay globally, or
override per individual scene with the "Mix per scene" option.

**New: 3-thumbnail B-roll preview.** See three candidate stock clips per scene
before render and pick which one fits.

**New: User-uploaded B-roll.** Bring your own screen recording, image, or
screenshot. We animate it into your video automatically.

**New: User-recorded voiceover.** Record your own voiceover in the browser
instead of using AI TTS.

**New: Caption burn-in with placement choice.** Top, Bottom, or Center caption
placement, all burned into the final MP4 directly.

**New: Inline video player.** Watch finished renders inside the app — no need
to open the CDN link in a new tab.

**New: Concurrent renders.** Kick off multiple renders at once; they progress
in parallel in the history list with live per-scene status ("Generating scene
2 of 5…", "Stitching scene 4 of 5…", etc.).

---

*Last updated: June 29, 2026*
