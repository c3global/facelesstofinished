/**
 * TimelineModal.jsx — Iter 60 / v1.20.0 Timeline Editor MVP.
 *
 * Opens from a completed Faceless render's history row. Fetches
 * `/studio/timeline/{job_id}`, lets the user flip a "Freeze last frame"
 * toggle per scene (plus a one-tap "Freeze all" helper), then POSTs to
 * `/studio/timeline/{job_id}/rerender` — that kicks off a fresh render
 * with `scene_overrides` applied. Result gets picked up by the parent
 * Studio history poller.
 *
 * Deliberately scoped to freeze-end for MVP. Drag-slider duration and
 * per-scene pause land in v2 once we have real per-sentence TTS timing.
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, Sparkles, Snowflake, Play, Loader2, AlertCircle } from "lucide-react";
import { apiClient } from "../App";

export default function TimelineModal({ jobId, open, onClose, onRerenderQueued }) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [data, setData] = useState(null);
  // Local override state — { [idx]: {freeze_end: bool} }
  const [overrides, setOverrides] = useState({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !jobId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      setData(null);
      setOverrides({});
      try {
        const r = await apiClient.get(`/studio/timeline/${jobId}`);
        if (cancelled) return;
        setData(r.data);
        // Seed overrides from server-side state so a re-open reflects last save.
        const seed = {};
        for (const s of (r.data.scenes || [])) {
          if (s.freeze_end) seed[s.idx] = { freeze_end: true };
        }
        setOverrides(seed);
      } catch (e) {
        if (cancelled) return;
        setErr(e?.response?.data?.detail || "Couldn't load timeline. Try again.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [jobId, open]);

  const toggleFreeze = (idx) => {
    setOverrides((prev) => {
      const next = { ...prev };
      if (next[idx]?.freeze_end) {
        delete next[idx];
      } else {
        next[idx] = { freeze_end: true };
      }
      return next;
    });
  };

  const freezeAll = () => {
    if (!data?.scenes) return;
    const next = {};
    for (const s of data.scenes) next[s.idx] = { freeze_end: true };
    setOverrides(next);
  };

  const clearAll = () => setOverrides({});

  const changedCount = useMemo(() => Object.keys(overrides).length, [overrides]);

  const submit = async () => {
    if (!jobId || submitting) return;
    setSubmitting(true);
    setErr("");
    try {
      const scene_overrides = data.scenes.map((s) => ({
        idx: s.idx,
        freeze_end: !!overrides[s.idx]?.freeze_end,
      }));
      const r = await apiClient.post(`/studio/timeline/${jobId}/rerender`, { scene_overrides });
      onRerenderQueued?.(r.data.job_id);
      onClose?.();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Re-render queue failed. Try again in a moment.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="timeline-modal-backdrop" data-testid="timeline-modal">
      <div className="timeline-modal">
        <header className="timeline-modal-head">
          <div>
            <p className="timeline-crumb">STUDIO · FACELESS · <b>EDIT TIMELINE</b></p>
            <h2 className="timeline-title">Scene timeline editor</h2>
          </div>
          <button
            className="timeline-close"
            data-testid="timeline-close"
            onClick={onClose}
            aria-label="Close timeline editor"
          >
            <X size={18} />
          </button>
        </header>

        {loading && (
          <div className="timeline-loading" data-testid="timeline-loading">
            <Loader2 size={20} className="timeline-spin" /> Loading scene data…
          </div>
        )}

        {err && !loading && (
          <div className="timeline-error" data-testid="timeline-error">
            <AlertCircle size={16} /> {err}
          </div>
        )}

        {data && !loading && (
          <>
            <p className="timeline-lede">
              Flip <b>Freeze last frame</b> on any scene where the stock clip loops behind
              a longer voiceover. Instead of looping, the last frame will hold until the
              sentence finishes — no more Groundhog Day B-roll.
            </p>

            <div className="timeline-summary" data-testid="timeline-summary">
              <div><span>{data.scenes.length}</span> scenes</div>
              <div><span>~{data.total_est_sec}s</span> total voiceover</div>
              <div><span>{data.aspect === "9_16" ? "9:16 Vertical" : "16:9 Horizontal"}</span></div>
              <div>
                <span data-testid="timeline-changed-count">{changedCount}</span> {changedCount === 1 ? "scene" : "scenes"} set to freeze
              </div>
            </div>

            <div className="timeline-actions-top">
              <button
                className="timeline-btn timeline-btn-ghost"
                onClick={freezeAll}
                data-testid="timeline-freeze-all"
              >
                <Snowflake size={13} /> Freeze all scenes
              </button>
              <button
                className="timeline-btn timeline-btn-ghost"
                onClick={clearAll}
                disabled={!changedCount}
                data-testid="timeline-clear-all"
              >
                Reset all
              </button>
            </div>

            <ul className="timeline-scene-grid" data-testid="timeline-scene-grid">
              {data.scenes.map((s) => {
                const frozen = !!overrides[s.idx]?.freeze_end;
                return (
                  <li
                    key={s.idx}
                    className={`timeline-scene ${frozen ? "is-frozen" : ""}`}
                    data-testid={`timeline-scene-${s.idx}`}
                  >
                    <div className="timeline-scene-thumb">
                      {s.video_url ? (
                        <video
                          src={s.video_url}
                          className="timeline-scene-thumb-video"
                          muted
                          playsInline
                          preload="metadata"
                        />
                      ) : (
                        <div className="timeline-scene-thumb-placeholder">
                          <Play size={20} />
                        </div>
                      )}
                      <span className="timeline-scene-badge">SCENE {s.idx + 1}</span>
                      <span className="timeline-scene-duration">{s.allocated_sec.toFixed(1)}s</span>
                      {frozen && (
                        <span className="timeline-scene-freeze-chip">
                          <Snowflake size={11} /> Freeze end
                        </span>
                      )}
                    </div>
                    <div className="timeline-scene-body">
                      <p className="timeline-scene-prompt">{s.prompt || s.search_query || "(no prompt)"}</p>
                      <label className="timeline-toggle-row">
                        <div>
                          <div className="timeline-toggle-name">Freeze on last frame</div>
                          <div className="timeline-toggle-desc">Hold the final frame instead of looping the clip</div>
                        </div>
                        <input
                          type="checkbox"
                          className="timeline-toggle-input"
                          checked={frozen}
                          onChange={() => toggleFreeze(s.idx)}
                          data-testid={`timeline-freeze-toggle-${s.idx}`}
                        />
                        <span className="timeline-toggle-track" aria-hidden>
                          <span className="timeline-toggle-dot" />
                        </span>
                      </label>
                    </div>
                  </li>
                );
              })}
            </ul>

            <footer className="timeline-modal-foot">
              <div className="timeline-foot-info">
                {changedCount === 0
                  ? "Nothing changed yet. Flip a toggle above, then re-render."
                  : `${changedCount} ${changedCount === 1 ? "scene" : "scenes"} will freeze on last frame. Re-render kicks a fresh Faceless job.`}
              </div>
              <div className="timeline-foot-actions">
                <button
                  className="timeline-btn timeline-btn-ghost"
                  onClick={onClose}
                  data-testid="timeline-cancel"
                >
                  Cancel
                </button>
                <button
                  className="timeline-btn timeline-btn-primary"
                  onClick={submit}
                  disabled={submitting || changedCount === 0}
                  data-testid="timeline-rerender"
                >
                  {submitting ? (
                    <><Loader2 size={13} className="timeline-spin" /> Queuing…</>
                  ) : (
                    <><Sparkles size={13} /> Re-render with fixes</>
                  )}
                </button>
              </div>
            </footer>
          </>
        )}
      </div>
    </div>
  );
}
