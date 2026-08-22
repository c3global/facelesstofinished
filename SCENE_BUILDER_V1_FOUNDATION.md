# Scene Builder v1 foundation

Scene Builder is the editable project layer that sits before Faceless48's render pipeline. It gives a customer a stable scene plan they can revise without purchasing media generation or starting a render.

## What this milestone includes

- Authenticated, Studio-entitled projects owned by one customer account.
- An immutable revision history with optimistic locking for safe autosave.
- Stable scene IDs across revisions.
- Exact transcript-to-scene mapping using zero-based, end-exclusive word ranges.
- Separate fields for a detailed visual direction and a concise stock-search query.
- Placeholders for stock, uploaded, and AI-generated visual choices.
- Edit metadata for clip trims, fit, motion, transitions, and last-frame freeze.
- Explicitly pending voiceover timing until a later audio-alignment step measures it.

The current Quick Render workflow is unchanged.

## Storage

Two MongoDB collections are added:

- `studio_projects`: one mutable pointer record per project, including its owner, title, aspect ratio, and current revision.
- `studio_project_revisions`: immutable snapshots of the script, voiceover state, and every scene.

The project pointer is advanced with a compare-and-set update. If two browser sessions save the same revision simultaneously, one succeeds and the other receives HTTP 409 instead of silently overwriting newer work.

## Scene contract

Each scene contains:

```json
{
  "id": "scn_<stable-id>",
  "order": 0,
  "narration": {
    "text": "Exact words spoken during this scene.",
    "word_start": 0,
    "word_end": 6,
    "start_ms": null,
    "end_ms": null,
    "timing_source": "pending"
  },
  "visual": {
    "source": "unassigned",
    "detailed_prompt": "Detailed direction suitable for an AI visual.",
    "stock_query": "short searchable visual keywords",
    "asset_id": null,
    "asset_url": null,
    "asset_kind": null,
    "alternatives": []
  },
  "edit": {
    "clip_start_ms": null,
    "clip_end_ms": null,
    "fit": "cover",
    "motion": "standard",
    "transition": "cut",
    "freeze_end": false
  }
}
```

Word ranges must be contiguous, non-overlapping, and cover the entire normalized script. Narration text must exactly equal the words in its range. This invariant is what will let the editor keep a chosen visual attached to the correct voiceover passage.

## API surface

All routes live under `/api` in production:

- `POST /api/studio/projects` — create a draft and initial scene plan.
- `GET /api/studio/projects` — list the signed-in customer's projects.
- `GET /api/studio/projects/{project_id}` — load the project and current revision.
- `PUT /api/studio/projects/{project_id}/revisions` — autosave a new immutable revision.
- `GET /api/studio/projects/{project_id}/revisions` — list revision metadata.
- `GET /api/studio/projects/{project_id}/revisions/{version}` — load a specific revision.

Every read and write is owner-scoped. Project IDs alone do not grant access.

## Cost and privacy boundary

`backend/scene_builder.py` has no imports or calls for FAL, KIE, HeyGen, Pexels, Pixabay, TTS, FFmpeg, Cloud Run dispatch, or any other provider. Creating, loading, and editing a project cannot trigger a paid request or render.

Uploaded media is represented only by an asset reference in this milestone. It continues to bypass AI and stock generation by design.

## Customer editor shell

The second milestone adds `/studio/scene-builder` and
`/studio/scene-builder/{project_id}` with:

1. A project list and "Create from script" flow.
2. Scene cards showing each exact narration passage and word range.
3. Separate detailed-prompt and stock-query editing.
4. Visual-source selection for stock, uploaded media, AI, or "decide later."
5. Existing uploaded-media library selection without an AI or stock call.
6. Debounced revision autosave with visible saved, error, and conflict states.
7. A visual-planning progress indicator.

Stock results and AI generation are deliberately disabled in the shell. The
customer can prepare and save those directions, but this preview cannot spend
provider credits.

Studio-entitled customers also receive a **Send to Scene Builder** action in
the Script Engine. It creates the saved project directly, preserves the
finished narration and original B-roll prompts, and opens the new project.
The action is hidden for accounts without Studio and the backend repeats the
entitlement check before writing anything.

## Next milestone

The next safe vertical slice is an explicit voiceover-alignment action that
fills `start_ms` and `end_ms` from measured audio, followed by non-generating
stock-result previews. Rendering should only be wired to a Scene Builder
revision after the editor can round-trip a project without data loss and the
alignment contract is tested against real narration audio.
