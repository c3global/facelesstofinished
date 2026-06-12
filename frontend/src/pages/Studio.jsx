import React, { useEffect, useMemo, useRef, useState } from "react";
import { UserCircle2, Mic, Ratio, Captions, Film, ChevronDown, Play, Trash2, Sparkles, Wand2, Loader2 } from "lucide-react";
import { apiClient, useAuth } from "../App";
import {
  AvatarPicker,
  VoicePicker,
  BRollSourcePicker,
  AspectPicker,
  CaptionsPicker,
  StockPicker,
} from "../components/Pickers";
import AdminRenderControl, { ConfirmRealRenderModal } from "../components/AdminRenderControl";

const MODES = { AVATAR: "avatar", FACELESS: "faceless" };
const MAX_SCENES = 12;
const SOURCE_HINT = {
  ai:      "An image will be generated from your prompt.",
  pexels:  "We'll search the Pexels stock library.",
  pixabay: "We'll search the Pixabay stock library.",
};
const SOURCE_SHORT = { ai: "AI", pexels: "Px", pixabay: "Pb" };

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}
const modeChipLabel = (m) => (m === MODES.AVATAR ? "Avatar" : "Faceless");

const SOURCE_PILL_OPTS = [
  { id: "ai", label: "AI" },
  { id: "pexels", label: "Pexels" },
  { id: "pixabay", label: "Pixabay" },
];

function SourcePills({ idx, current, onPick }) {
  return (
    <div className="scene-sources" role="radiogroup" data-testid={`scene-sources-${idx}`}>
      {SOURCE_PILL_OPTS.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={current === o.id}
          className={`source-pill ${current === o.id ? "is-on" : ""}`}
          data-source={o.id}
          data-testid={`scene-source-${idx}-${o.id}`}
          onClick={() => onPick(idx, o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function Studio() {
  // Mode
  const [mode, setMode] = useState(MODES.AVATAR);

  // Script
  const [script, setScript] = useState("");

  // Banner shown after a Send-to-Studio handoff
  const [handoffBanner, setHandoffBanner] = useState(null);
  const handoffBannerTimer = useRef(null);

  // Pick up a script handed off from /scripts via localStorage (one-shot).
  // Payload is JSON { script, brollPrompts, sourceMode, topic, ts } as of iteration 5,
  // with backward-compat for a plain-string payload from older versions.
  useEffect(() => {
    try {
      const raw = localStorage.getItem("f48_handoff_script");
      if (!raw) return;
      localStorage.removeItem("f48_handoff_script");
      let payload;
      try { payload = JSON.parse(raw); }
      catch { payload = { script: raw, brollPrompts: [], sourceMode: null, topic: null }; }

      if (payload.script) setScript(payload.script);
      if (Array.isArray(payload.brollPrompts) && payload.brollPrompts.length) {
        setBulkPrompts(payload.brollPrompts.join("\n"));
        setSceneOverrides(payload.brollPrompts.map(() => ({})));
      }
      // Default mode by source: shorts → Faceless (uses voiceover + B-roll natively),
      // long → stay on Avatar (talking head) but the B-roll prompts are staged.
      if (payload.sourceMode === "shorts") setMode(MODES.FACELESS);

      const wordCount = (payload.script || "").trim().split(/\s+/).filter(Boolean).length;
      setHandoffBanner({
        words: wordCount,
        prompts: payload.brollPrompts?.length || 0,
        sourceMode: payload.sourceMode || null,
        topic: payload.topic || null,
      });
      if (handoffBannerTimer.current) clearTimeout(handoffBannerTimer.current);
      handoffBannerTimer.current = setTimeout(() => setHandoffBanner(null), 10000);
    } catch {}
    return () => {
      if (handoffBannerTimer.current) clearTimeout(handoffBannerTimer.current);
    };
  }, []);

  // Auto-generated B-roll prompts state
  const [generatingPrompts, setGeneratingPrompts] = useState(false);
  const [promptsErr, setPromptsErr] = useState("");

  // Settings
  const [aspect, setAspect] = useState("9_16");
  const [captions, setCaptions] = useState(true);
  const captionsTouched = useRef(false);
  useEffect(() => {
    if (!captionsTouched.current) setCaptions(aspect === "9_16");
  }, [aspect]);

  // Avatar mode picks
  const [avatar, setAvatar] = useState(null);
  const [voice, setVoice] = useState(null);

  // Faceless mode picks
  const [ttsVoice, setTtsVoice] = useState(null);
  const [brollSource, setBrollSource] = useState("pexels"); // global default
  // Bulk prompts model:
  // - bulkPrompts: raw textarea text
  // - sceneOverrides: per-index { source?, pick? } overrides
  const [bulkPrompts, setBulkPrompts] = useState("");
  const [sceneOverrides, setSceneOverrides] = useState([]); // [{source?, pick?}]

  // Render state
  const [render, setRender] = useState(null);
  const [history, setHistory] = useState([]);
  const [renderErr, setRenderErr] = useState("");
  const pollRef = useRef(null);

  // Admin-only state — never persisted: defaults OFF every page load.
  const { user } = useAuth();
  const isAdmin = !!user?.isAdmin;
  const [useReal, setUseReal] = useState(false);
  const [confirmReal, setConfirmReal] = useState(null);  // {dollars} when open

  // Modal state
  const [modal, setModal] = useState(null);
  const [stockModal, setStockModal] = useState({ open: false, idx: -1 });

  const closeModal = () => setModal(null);

  // ---- Derive scene lines from textarea ----
  const sceneLines = useMemo(() => {
    return bulkPrompts
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .slice(0, MAX_SCENES);
  }, [bulkPrompts]);

  // Keep sceneOverrides array length aligned with line count
  useEffect(() => {
    setSceneOverrides((prev) => {
      const next = sceneLines.map((_, i) => prev[i] || {});
      return next;
    });
  }, [sceneLines.length]);

  // The fully-resolved scenes (line + effective source + pick)
  const scenes = useMemo(() => {
    return sceneLines.map((prompt, i) => {
      const ov = sceneOverrides[i] || {};
      // When global is "mix" we leave source undefined unless overridden.
      const effective = ov.source ?? (brollSource === "mix" ? null : brollSource);
      return {
        prompt,
        source: effective,
        pick: ov.pick || null,
      };
    });
  }, [sceneLines, sceneOverrides, brollSource]);

  // ---- Load history on mount ----
  useEffect(() => {
    loadHistory();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const loadHistory = async () => {
    try {
      const r = await apiClient.get("/studio/history");
      setHistory(r.data.items || []);
    } catch { /* noop */ }
  };

  // ---- Validation ----
  const canGenerate = useMemo(() => {
    if (!script.trim()) return false;
    if (mode === MODES.AVATAR) return !!avatar && !!voice;
    if (!ttsVoice) return false;
    if (scenes.length === 0) return false;
    // Every scene needs a resolved source (mix mode requires explicit pick per scene)
    if (scenes.some((s) => !s.source)) return false;
    return true;
  }, [script, mode, avatar, voice, ttsVoice, scenes]);

  // Build a payload from the current form state. Reused by the live cost
  // estimate request and the actual /studio/render request below.
  const buildPayload = () => ({
    mode,
    script,
    aspect,
    captions,
    avatar_id: mode === MODES.AVATAR ? avatar?.id : null,
    voice_id: mode === MODES.AVATAR ? voice?.id : null,
    tts_voice_id: mode === MODES.FACELESS ? ttsVoice?.id : null,
    broll_source: mode === MODES.FACELESS ? brollSource : null,
    scenes: mode === MODES.FACELESS ? scenes.map((s) => ({
      source: s.source,
      prompt: s.prompt,
      video_url: s.pick?.video_url || null,
      thumb: s.pick?.thumb || null,
    })) : [],
  });

  // ---- Generate ----
  // Admin + useReal flow: fetch a fresh estimate, open the confirm modal,
  // then fire the render with `dry_run: false` after the modal's 1s-delayed
  // confirm button is clicked. Customers (and admins with useReal=false)
  // simply fire the render — the backend handles the rest with the env
  // default dry_run.
  const fireRender = async (dryRunOverride) => {
    setRenderErr("");
    try {
      const body = buildPayload();
      if (dryRunOverride !== undefined) body.dry_run = dryRunOverride;
      const r = await apiClient.post("/studio/render", body);
      setRender(r.data);
      pollStatus(r.data.id);
    } catch (e) {
      setRenderErr(e?.response?.data?.detail || "Could not start render. Try again.");
    }
  };

  const generate = async () => {
    if (!isAdmin || !useReal) {
      // Customer path — backend handles dry_run from env default.
      fireRender(undefined);
      return;
    }
    // Admin "Use real render" path — re-fetch estimate then open confirm modal.
    try {
      const estR = await apiClient.post("/studio/render/estimate", buildPayload());
      if (estR.data.exceeds_cap) {
        setRenderErr(`Estimated $${estR.data.estimated_cost_dollars.toFixed(2)} exceeds the $${estR.data.cap_dollars.toFixed(2)} hard cap.`);
        return;
      }
      setConfirmReal({ dollars: estR.data.estimated_cost_dollars.toFixed(2) });
    } catch (e) {
      setRenderErr(e?.response?.data?.detail || "Could not estimate cost.");
    }
  };

  const pollStatus = (jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiClient.get(`/studio/render/${jobId}`);
        setRender(r.data);
        if (r.data.status === "complete" || r.data.status === "failed") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadHistory();
        }
      } catch {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 1500);
  };

  const deleteRender = async (jobId) => {
    try {
      await apiClient.delete(`/studio/render/${jobId}`);
      setHistory((h) => h.filter((r) => r.id !== jobId));
    } catch (e) {
      alert(e?.response?.data?.detail || "Could not delete.");
    }
  };

  // ---- Generate B-roll prompts from script via Claude ----
  const generatePromptsFromScript = async () => {
    if (!script.trim()) return;
    setPromptsErr("");
    setGeneratingPrompts(true);
    try {
      const r = await apiClient.post("/studio/broll-prompts", { script });
      const lines = (r.data.prompts || []).slice(0, 12);
      setBulkPrompts(lines.join("\n"));
      setSceneOverrides(lines.map(() => ({})));
    } catch (e) {
      setPromptsErr(e?.response?.data?.detail || "Could not generate prompts. Try again.");
    } finally {
      setGeneratingPrompts(false);
    }
  };

  // ---- Scene source override ----
  const setSceneSource = (idx, src) => {
    setSceneOverrides((prev) => {
      const next = [...prev];
      next[idx] = { ...(next[idx] || {}), source: src, pick: null };
      return next;
    });
  };
  const setScenePick = (idx, pick) => {
    setSceneOverrides((prev) => {
      const next = [...prev];
      next[idx] = { ...(next[idx] || {}), pick };
      return next;
    });
  };

  // ---- Chips ----
  const chipAvatar = (
    <button className={`chip ${avatar ? "is-set" : ""}`} data-testid="chip-avatar" onClick={() => setModal("avatar")}>
      {avatar?.preview_image_url
        ? <img src={avatar.preview_image_url} alt="" className="chip-thumb" />
        : <span className="chip-icon"><UserCircle2 size={16} /></span>}
      <span className="chip-label">{avatar ? avatar.name : "Avatar"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  const chipVoice = (
    <button className={`chip ${voice ? "is-set" : ""}`} data-testid="chip-voice" onClick={() => setModal("voice")}>
      <span className="chip-icon"><Mic size={14} /></span>
      <span className="chip-label">{voice ? `Voice · ${voice.name}` : "Voice"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  const chipTtsVoice = (
    <button className={`chip ${ttsVoice ? "is-set" : ""}`} data-testid="chip-tts-voice" onClick={() => setModal("tts-voice")}>
      <span className="chip-icon"><Mic size={14} /></span>
      <span className="chip-label">{ttsVoice ? `Voice · ${ttsVoice.name}` : "Voice"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  const chipAspect = (
    <button className="chip is-set" data-testid="chip-aspect" onClick={() => setModal("aspect")}>
      <span className="chip-icon"><Ratio size={14} /></span>
      <span className="chip-label">{aspect === "9_16" ? "9:16 Vertical" : "16:9 Horizontal"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  const chipCaptions = (
    <button className="chip is-set" data-testid="chip-captions" onClick={() => setModal("captions")}>
      <span className="chip-icon"><Captions size={14} /></span>
      <span className="chip-label">{captions ? "Captions ON" : "Captions OFF"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  const brollChipLabel = {
    ai: "B-Roll · AI",
    pexels: "B-Roll · Pexels",
    pixabay: "B-Roll · Pixabay",
    mix: "B-Roll · Mix",
  }[brollSource] || "B-Roll";
  const chipBroll = (
    <button className="chip is-set" data-testid="chip-broll" onClick={() => setModal("broll")}>
      <span className="chip-icon"><Film size={14} /></span>
      <span className="chip-label">{brollChipLabel}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  // ---- Source pills handled by hoisted SourcePills component ----

  return (
    <main className="studio-main" data-mode={mode} data-testid="studio-page">
      {/* Hero */}
      <div className="studio-hero">
        <p className="studio-eyebrow" data-testid="studio-eyebrow">
          Faceless to Finished · Video Engine
        </p>
        <h1 className="studio-title">Turn your script into a finished video.</h1>
        <p className="studio-sub">
          Paste your script, pick your look in two clicks, and we&rsquo;ll render the final cut — captions, voice, footage and all.
        </p>
      </div>

      {/* Handoff banner — shown briefly after Send-to-Studio */}
      {handoffBanner && (
        <div className="handoff-banner" data-testid="handoff-banner">
          <div className="handoff-banner-icon"><Sparkles size={16} /></div>
          <div className="handoff-banner-body">
            <strong>Loaded from Script Engine</strong>
            <span>
              {handoffBanner.words.toLocaleString()}-word script
              {handoffBanner.prompts > 0 && ` + ${handoffBanner.prompts} B-roll prompt${handoffBanner.prompts === 1 ? "" : "s"}`}
              {handoffBanner.topic && ` — "${handoffBanner.topic}"`}
              {handoffBanner.prompts > 0 && mode === MODES.AVATAR && (
                <>
                  {" · "}
                  <button
                    type="button"
                    className="handoff-banner-cta"
                    data-testid="handoff-switch-faceless"
                    onClick={() => setMode(MODES.FACELESS)}
                  >Switch to Faceless to use the B-roll prompts →</button>
                </>
              )}
            </span>
          </div>
          <button
            type="button"
            className="handoff-banner-close"
            data-testid="handoff-banner-close"
            aria-label="Dismiss"
            onClick={() => setHandoffBanner(null)}
          >×</button>
        </div>
      )}

      {/* Mode toggle */}
      <div className="mode-toggle" role="tablist" data-testid="mode-toggle">
        <button
          role="tab"
          data-mode="avatar"
          className={`mode-opt ${mode === MODES.AVATAR ? "is-active" : ""}`}
          data-testid="mode-avatar"
          onClick={() => setMode(MODES.AVATAR)}
        >
          <UserCircle2 size={14} /> Avatar
        </button>
        <button
          role="tab"
          data-mode="faceless"
          className={`mode-opt ${mode === MODES.FACELESS ? "is-active" : ""}`}
          data-testid="mode-faceless"
          onClick={() => setMode(MODES.FACELESS)}
        >
          <Film size={14} /> Faceless
        </button>
      </div>

      {/* Script */}
      <div className="script-block">
        <span className="script-label">Script</span>
        <textarea
          className="script-area"
          data-testid="script-textarea"
          placeholder={mode === MODES.AVATAR
            ? "Paste the script your avatar will read…"
            : "Paste the script for your voiceover."}
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={6}
        />
        <div className="script-meta">
          <span data-testid="script-word-count">{script.trim() ? script.trim().split(/\s+/).length : 0} words</span>
          <span>~{Math.max(15, Math.round(script.split(/\s+/).filter(Boolean).length / 2.5))}s read time</span>
        </div>
      </div>

      {/* Chip row */}
      <div className="chip-row" data-testid="chip-row">
        {mode === MODES.AVATAR ? (
          <>{chipAvatar}{chipVoice}{chipAspect}{chipCaptions}</>
        ) : (
          <>{chipTtsVoice}{chipBroll}{chipAspect}{chipCaptions}</>
        )}
      </div>

      {/* Faceless: Bulk prompts + scene list */}
      {mode === MODES.FACELESS && (
        <div className="scene-section" data-testid="scene-section">
          <div className="scene-section-head">
            <span className="scene-section-title">B-Roll prompts</span>
            <div className="scene-section-actions">
              <button
                type="button"
                className="generate-prompts-btn"
                data-testid="generate-prompts-btn"
                disabled={!script.trim() || generatingPrompts}
                onClick={generatePromptsFromScript}
                title={!script.trim() ? "Paste a script above first" : ""}
              >
                {generatingPrompts ? <Loader2 size={12} className="spin" /> : <Wand2 size={12} />}
                {generatingPrompts ? "Generating…" : "Generate from script"}
              </button>
              <span className="scene-section-count" data-testid="scene-count">
                <strong>{sceneLines.length}</strong> {sceneLines.length === 1 ? "scene" : "scenes"} · up to {MAX_SCENES}
              </span>
            </div>
          </div>
          {promptsErr && <p className="cta-error" data-testid="prompts-err">{promptsErr}</p>}
          <textarea
            className="bulk-prompts"
            data-testid="bulk-prompts"
            placeholder={`One prompt per line. Each line becomes one scene. Up to ${MAX_SCENES} scenes.\n\nsunrise over mountains\nentrepreneur working late at her laptop\nlaughing customer holding a product`}
            value={bulkPrompts}
            onChange={(e) => {
              // Cap to MAX_SCENES non-empty lines while preserving formatting
              const text = e.target.value;
              const lines = text.split(/\r?\n/);
              let count = 0;
              const capped = [];
              for (const ln of lines) {
                if (ln.trim()) {
                  if (count >= MAX_SCENES) break;
                  count++;
                }
                capped.push(ln);
              }
              setBulkPrompts(capped.join("\n"));
            }}
            rows={6}
          />

          {/* Resolved scenes (read-only prompt + per-scene source pills) */}
          {sceneLines.length > 0 && (
            <div className="scene-list" data-testid="scene-list">
              {scenes.map((s, i) => (
                <div className="scene-card" key={i} data-testid={`scene-card-${i}`}>
                  <div className="scene-card-head">
                    <span className="scene-num">Scene {i + 1}</span>
                    <span className="scene-prompt-readonly">{s.prompt}</span>
                  </div>
                  <SourcePills idx={i} current={s.source} onPick={setSceneSource} />
                  <div className="scene-hint" data-testid={`scene-hint-${i}`}>
                    {s.source ? (
                      <>
                        {s.source === "ai" && <Sparkles size={12} />}
                        {s.source === "pexels" && <Film size={12} />}
                        {s.source === "pixabay" && <Film size={12} />}
                        <span>{SOURCE_HINT[s.source]}</span>
                        {(s.source === "pexels" || s.source === "pixabay") && (
                          <button
                            type="button"
                            className="scene-hint-pick"
                            data-testid={`scene-pick-${i}`}
                            onClick={() => setStockModal({ open: true, idx: i })}
                          >
                            {s.pick ? (
                              <>
                                {s.pick.thumb && <img src={s.pick.thumb} alt="" className="scene-hint-thumb" style={{ verticalAlign: -6, marginRight: 6 }} />}
                                Change clip
                              </>
                            ) : "Pre-pick a clip"}
                          </button>
                        )}
                      </>
                    ) : (
                      <span style={{ color: "var(--warning)" }}>Pick a source for this scene.</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Storyboard */}
      {mode === MODES.FACELESS && sceneLines.length > 0 && (
        <div className="storyboard-block" data-testid="storyboard-block">
          <div className="storyboard-head">
            <span className="storyboard-title">Storyboard</span>
          </div>
          <div className="storyboard-strip" data-testid="storyboard-strip">
            {scenes.map((s, i) => (
              <button
                className="storyboard-card"
                key={i}
                data-testid={`storyboard-card-${i}`}
                onClick={() => {
                  if (s.source === "pexels" || s.source === "pixabay") setStockModal({ open: true, idx: i });
                }}
              >
                <div className={`storyboard-thumb ${aspect === "16_9" ? "is-16-9" : ""}`}>
                  <span className="storyboard-idx">{i + 1}</span>
                  {s.source && (
                    <span className="storyboard-source-badge" data-source={s.source}>
                      {SOURCE_SHORT[s.source]}
                    </span>
                  )}
                  {s.pick?.thumb && <img src={s.pick.thumb} alt="" />}
                </div>
                <div className="storyboard-meta">
                  <div className="storyboard-prompt">{s.prompt}</div>
                  <div className={`storyboard-status ${s.pick || s.source === "ai" ? "is-ready" : ""}`}>
                    {!s.source ? "Pick source" : s.source === "ai" ? "AI scene" : (s.pick ? "Clip ready" : "Auto search")}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Admin-only: dry-run override + live cost estimate */}
      {isAdmin && (
        <AdminRenderControl
          payload={buildPayload()}
          useReal={useReal}
          setUseReal={setUseReal}
        />
      )}

      {/* Generate */}
      <div className="cta-block">
        <button
          className="cta-btn"
          data-testid="generate-btn"
          disabled={!canGenerate || (render && render.status !== "complete" && render.status !== "failed")}
          onClick={generate}
        >
          {isAdmin && useReal ? "Render (real)" : "Render your video"}
        </button>
        {!canGenerate && (
          <p className="cta-hint" data-testid="cta-hint">
            {!script.trim()
              ? "Paste a script to begin."
              : mode === MODES.AVATAR
                ? !avatar ? "Pick an avatar." : !voice ? "Pick a voice." : ""
                : !ttsVoice ? "Pick a voice."
                  : scenes.length === 0 ? "Add at least one B-roll prompt."
                    : "Pick a source for every scene."}
          </p>
        )}
        {renderErr && <p className="cta-error" data-testid="cta-error">{renderErr}</p>}
      </div>

      {/* Active render */}
      {render && (
        <div className="render-card" data-testid="render-card">
          <div className="render-status">
            <span className="render-status-label" data-testid="render-status-label">
              {render.progress_label || render.status}
            </span>
            <span className="render-status-pct" data-testid="render-progress">{render.progress}%</span>
          </div>
          <div className="render-bar">
            <div className="render-bar-fill" style={{ width: `${render.progress}%` }} />
          </div>
          {render.status === "complete" && render.result_url && (
            <video className="render-video" data-testid="render-video" src={render.result_url} controls playsInline />
          )}
          {render.status === "failed" && (
            <p style={{ color: "var(--danger)", margin: 0 }}>Render failed: {render.error || "unknown error"}</p>
          )}
        </div>
      )}

      {/* History */}
      <div className="history-block" data-testid="history-block">
        <div className="history-head">Recent renders</div>
        {history.length === 0 ? (
          <div className="history-empty" data-testid="history-empty">No renders yet. Your finished videos will appear here.</div>
        ) : (
          <div className="history-list">
            {history.map((r) => (
              <div className="history-row" key={r.id} data-testid={`history-row-${r.id}`}>
                <div className="history-meta">
                  <span className={`history-chip is-${r.mode}`}>{modeChipLabel(r.mode)}</span>
                  <span className={`history-chip is-${r.status === "complete" ? "complete" : r.status === "failed" ? "failed" : "progress"}`}>
                    {r.status}
                  </span>
                  <span className="history-date">{fmtDate(r.created_at)}</span>
                </div>
                <div className="history-actions">
                  {r.status === "complete" && r.result_url && (
                    <a className="icon-btn" href={r.result_url} target="_blank" rel="noreferrer" data-testid={`history-play-${r.id}`} aria-label="Play">
                      <Play size={14} />
                    </a>
                  )}
                  <button
                    className="icon-btn is-danger"
                    data-testid={`history-delete-${r.id}`}
                    onClick={() => deleteRender(r.id)}
                    disabled={r.status !== "complete" && r.status !== "failed"}
                    aria-label="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modals */}
      <AvatarPicker open={modal === "avatar"} onClose={closeModal} value={avatar} onPick={setAvatar} />
      <VoicePicker open={modal === "voice"} onClose={closeModal} value={voice} onPick={setVoice} source="heygen" />
      <VoicePicker open={modal === "tts-voice"} onClose={closeModal} value={ttsVoice} onPick={setTtsVoice} source="tts" />
      <BRollSourcePicker
        open={modal === "broll"}
        onClose={closeModal}
        value={brollSource}
        onPick={(src) => {
          setBrollSource(src);
          // Clear per-scene overrides so the new global takes effect (except when going to "mix")
          if (src !== "mix") setSceneOverrides((prev) => prev.map(() => ({})));
        }}
      />
      <AspectPicker open={modal === "aspect"} onClose={closeModal} value={aspect} onPick={setAspect} />
      <CaptionsPicker open={modal === "captions"} onClose={closeModal} value={captions} onPick={(v) => { captionsTouched.current = true; setCaptions(v); }} />
      <StockPicker
        open={stockModal.open}
        sceneIdx={stockModal.idx}
        defaultSource={
          stockModal.idx >= 0 && scenes[stockModal.idx]?.source === "pixabay" ? "pixabay" : "pexels"
        }
        query={stockModal.idx >= 0 ? scenes[stockModal.idx]?.prompt : ""}
        aspect={aspect}
        onClose={() => setStockModal({ open: false, idx: -1 })}
        onPick={(r) => {
          if (stockModal.idx >= 0) setScenePick(stockModal.idx, r);
        }}
      />

      {/* Admin: confirm-real-render modal */}
      {confirmReal && (
        <ConfirmRealRenderModal
          estimateDollars={confirmReal.dollars}
          onCancel={() => setConfirmReal(null)}
          onConfirm={() => {
            setConfirmReal(null);
            fireRender(false);
          }}
        />
      )}
    </main>
  );
}
