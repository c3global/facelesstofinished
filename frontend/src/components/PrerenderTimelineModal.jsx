/**
 * PrerenderTimelineModal.jsx — v1.20.10 / Iter 68 Batch 2.
 *
 * Pre-render Timeline Editor. Fetches the full pipeline manifest from
 * /studio/render/preview (script → beats → per-scene TTS → primary +
 * cutaway B-roll URLs) and shows it as an editable timeline BEFORE the
 * user commits to rendering.
 *
 * User actions inside the modal:
 *   • See exactly what will render (scenes, real per-scene audio duration
 *     from Kokoro, chosen primary + cutaway clips as thumbnails).
 *   • Remove any cutaway they don't like (a scene with too many clips
 *     can drop to 1-3).
 *   • Toggle "freeze last frame" per scene (existing behavior, exposed
 *     here for the first time pre-render).
 *   • Confirm → commits to /studio/render with `preview_id`, which
 *     reuses the exact TTS + B-roll from the preview (no regeneration).
 *
 * Scope decisions (v1):
 *   • No drag-to-reorder scenes — Batch 3.
 *   • No swap-primary-clip via Pexels re-search — Batch 3.
 *   • Cutaway thumbnails are fetch previews; final render might resample
 *     if a URL 404s (unlikely for fresh Pexels URLs).
 */
import React, { useEffect, useState } from "react";
import { X, Loader2, AlertCircle, Snowflake, Play, Trash2, Film } from "lucide-react";
import { apiClient } from "../App";

function formatDuration(ms) {
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${rem.toString().padStart(2, "0")}s`;
}

export default function PrerenderTimelineModal({
  isOpen,
  onClose,
  script,
  aspect,
  brollSource,
  ttsVoiceId,
  renderPayloadExtras, // any other RenderRequest fields the caller wants preserved
  onRenderStarted,
}) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  // Local edits: per-idx { freeze_end?: bool, clip_urls?: string[] }
  const [overrides, setOverrides] = useState({});

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      setPreview(null);
      setOverrides({});
      try {
        const r = await apiClient.post("/studio/render/preview", {
          script,
          aspect,
          broll_source: brollSource || "pexels",
          tts_voice_id: ttsVoiceId || "af_heart",
        });
        if (cancelled) return;
        setPreview(r.data);
      } catch (e) {
        if (cancelled) return;
        setErr(e?.response?.data?.detail || "Couldn't build the timeline preview. Try again.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, script, aspect, brollSource, ttsVoiceId]);

  const scenes = preview?.scenes || [];

  const currentClips = (scene) => {
    const ov = overrides[scene.idx];
    if (ov?.clip_urls) return ov.clip_urls;
    return scene.clip_urls || [];
  };

  const removeCutaway = (sceneIdx, clipIdx) => {
    setOverrides((prev) => {
      const scene = scenes.find((s) => s.idx === sceneIdx);
      if (!scene) return prev;
      const current = currentClips(scene);
      // Can't remove the primary clip (idx 0).
      if (clipIdx === 0 || current.length <= 1) return prev;
      const next = { ...prev };
      const list = [...current];
      list.splice(clipIdx, 1);
      next[sceneIdx] = { ...(prev[sceneIdx] || {}), clip_urls: list };
      return next;
    });
  };

  const toggleFreeze = (sceneIdx) => {
    setOverrides((prev) => {
      const next = { ...prev };
      const isOn = !!prev[sceneIdx]?.freeze_end;
      next[sceneIdx] = { ...(prev[sceneIdx] || {}), freeze_end: !isOn };
      return next;
    });
  };

  const editedCount = Object.keys(overrides).length;
  const totalDurMs = scenes.reduce((s, x) => s + (x.duration_ms || 0), 0);
  const totalClipCount = scenes.reduce(
    (s, x) => s + currentClips(x).length,
    0,
  );

  const commitRender = async () => {
    if (!preview?.preview_id) return;
    setSubmitting(true);
    setErr("");
    try {
      // 1) Persist any local edits back to the preview.
      if (editedCount > 0) {
        const editedScenes = scenes.map((s) => {
          const ov = overrides[s.idx] || {};
          return {
            ...s,
            clip_urls: currentClips(s),
            freeze_end: ov.freeze_end ?? false,
          };
        });
        await apiClient.post(`/studio/render/preview/${preview.preview_id}`, {
          scenes: editedScenes,
        });
      }
      // 2) Trigger the actual render with preview_id. The backend
      // reads the (potentially edited) preview manifest and reuses
      // TTS + clip URLs verbatim.
      const scene_overrides = Object.entries(overrides)
        .filter(([, v]) => v?.freeze_end)
        .map(([idx]) => ({ idx: parseInt(idx, 10), freeze_end: true }));

      const renderPayload = {
        mode: "faceless",
        script,
        aspect,
        broll_source: brollSource,
        tts_voice_id: ttsVoiceId,
        preview_id: preview.preview_id,
        scene_overrides,
        ...(renderPayloadExtras || {}),
      };
      const r = await apiClient.post("/studio/render", renderPayload);
      if (onRenderStarted && r.data?.id) {
        onRenderStarted(r.data.id);
      }
      onClose?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Couldn't start the render. Try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="timeline-modal-backdrop" data-testid="prerender-timeline-backdrop" onClick={onClose}>
      <div
        className="timeline-modal"
        onClick={(e) => e.stopPropagation()}
        data-testid="prerender-timeline-modal"
      >
        <header className="timeline-modal-header">
          <div className="timeline-modal-title">
            <Film size={18} />
            <span>Pre-render Timeline</span>
          </div>
          <button
            className="timeline-modal-close"
            onClick={onClose}
            data-testid="prerender-timeline-close"
          >
            <X size={16} />
          </button>
        </header>

        {loading && (
          <div className="timeline-modal-loading" data-testid="prerender-timeline-loading">
            <Loader2 className="spin" size={20} />
            <p>Building your timeline…</p>
            <p className="hint">Generating voiceover per scene + fetching B-roll thumbnails. This takes ~10–45 seconds.</p>
          </div>
        )}

        {err && (
          <div className="timeline-modal-error" data-testid="prerender-timeline-error">
            <AlertCircle size={16} />
            <span>{err}</span>
          </div>
        )}

        {preview && !loading && (
          <>
            <div className="timeline-summary" data-testid="prerender-timeline-summary">
              <div className="timeline-summary-stat">
                <strong>{preview.total_scene_count}</strong>&nbsp;scenes
              </div>
              <div className="timeline-summary-stat">
                <strong>{formatDuration(totalDurMs)}</strong>&nbsp;video
              </div>
              <div className="timeline-summary-stat">
                <strong>{totalClipCount}</strong>&nbsp;total clips
              </div>
              {editedCount > 0 && (
                <div className="timeline-summary-edited" data-testid="prerender-timeline-edited-badge">
                  {editedCount} edit{editedCount === 1 ? "" : "s"}
                </div>
              )}
            </div>

            <div className="timeline-scenes-scroll" data-testid="prerender-timeline-scenes">
              {scenes.map((scene) => {
                const clips = currentClips(scene);
                const ov = overrides[scene.idx] || {};
                const dur = scene.duration_ms || 0;
                return (
                  <div
                    key={scene.idx}
                    className="timeline-scene-row"
                    data-testid={`prerender-scene-row-${scene.idx}`}
                  >
                    <div className="timeline-scene-num">{scene.idx + 1}</div>
                    <div className="timeline-scene-body">
                      <div className="timeline-scene-text">{scene.text}</div>
                      <div className="timeline-scene-meta">
                        <span>{formatDuration(dur)}</span>
                        <span>·</span>
                        <span>{clips.length} clip{clips.length === 1 ? "" : "s"}</span>
                        {scene.audio_url && (
                          <>
                            <span>·</span>
                            <a
                              href={scene.audio_url}
                              target="_blank"
                              rel="noreferrer"
                              className="timeline-audio-link"
                              data-testid={`prerender-audio-link-${scene.idx}`}
                            >
                              <Play size={11} /> Preview voice
                            </a>
                          </>
                        )}
                      </div>
                      <div className="timeline-clip-strip">
                        {clips.map((url, ci) => (
                          <div
                            key={`${scene.idx}-${ci}-${url}`}
                            className={`timeline-clip-thumb ${ci === 0 ? "is-primary" : "is-cutaway"}`}
                            data-testid={`prerender-clip-${scene.idx}-${ci}`}
                          >
                            <video
                              src={url}
                              muted
                              playsInline
                              preload="metadata"
                              onMouseEnter={(e) => e.currentTarget.play()}
                              onMouseLeave={(e) => {
                                e.currentTarget.pause();
                                e.currentTarget.currentTime = 0;
                              }}
                            />
                            <span className="timeline-clip-label">
                              {ci === 0 ? "Primary" : `Cut ${ci}`}
                            </span>
                            {ci > 0 && clips.length > 1 && (
                              <button
                                className="timeline-clip-remove"
                                onClick={() => removeCutaway(scene.idx, ci)}
                                title="Remove this cutaway"
                                data-testid={`prerender-clip-remove-${scene.idx}-${ci}`}
                              >
                                <Trash2 size={11} />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="timeline-scene-actions">
                      <button
                        className={`timeline-freeze-btn ${ov.freeze_end ? "is-on" : ""}`}
                        onClick={() => toggleFreeze(scene.idx)}
                        title={ov.freeze_end ? "Freeze last frame ON" : "Freeze last frame OFF"}
                        data-testid={`prerender-freeze-toggle-${scene.idx}`}
                      >
                        <Snowflake size={12} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <footer className="timeline-modal-footer">
              <button
                className="timeline-footer-secondary"
                onClick={onClose}
                disabled={submitting}
                data-testid="prerender-timeline-cancel"
              >
                Cancel
              </button>
              <button
                className="timeline-footer-primary"
                onClick={commitRender}
                disabled={submitting || scenes.length === 0}
                data-testid="prerender-timeline-render-btn"
              >
                {submitting ? (
                  <>
                    <Loader2 className="spin" size={14} /> Starting render…
                  </>
                ) : (
                  <>Render this video</>
                )}
              </button>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}
