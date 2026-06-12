import React, { useEffect, useMemo, useRef, useState } from "react";
import { UserCircle2, Mic, Ratio, Captions, Film, ChevronDown, Play, Trash2, Plus } from "lucide-react";
import { apiClient } from "../App";
import {
  AvatarPicker,
  VoicePicker,
  BRollSourcePicker,
  AspectPicker,
  CaptionsPicker,
  StockPicker,
} from "../components/Pickers";

const MODES = { AVATAR: "avatar", FACELESS: "faceless" };

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch { return iso; }
}

function modeChipLabel(mode) {
  return mode === MODES.AVATAR ? "Avatar" : "Faceless";
}

export default function Studio() {
  // Mode
  const [mode, setMode] = useState(MODES.AVATAR);

  // Script
  const [script, setScript] = useState("");

  // Settings
  const [aspect, setAspect] = useState("9_16");
  // Captions default mirrors aspect (ON for vertical, OFF for horizontal)
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
  const [brollSource, setBrollSource] = useState("pexels");
  const [scenes, setScenes] = useState([
    { prompt: "", pick: null },
  ]);

  // Render state
  const [render, setRender] = useState(null);
  const [history, setHistory] = useState([]);
  const [renderErr, setRenderErr] = useState("");
  const pollRef = useRef(null);

  // Modal state
  const [modal, setModal] = useState(null);
  const [stockModal, setStockModal] = useState({ open: false, idx: -1 });

  const closeModal = () => setModal(null);

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

  // ---- Storyboard scenes (auto-suggest from script paragraphs in faceless mode) ----
  const scriptSegments = useMemo(() => {
    return script
      .split(/\n{2,}|(?<=[.!?])\s+(?=[A-Z])/)
      .map((s) => s.trim())
      .filter(Boolean);
  }, [script]);

  // Pad scenes to match segments (only fills empty prompts)
  useEffect(() => {
    if (mode !== MODES.FACELESS) return;
    if (scriptSegments.length === 0) return;
    setScenes((prev) => {
      // Auto-create new scenes for new segments if user hasn't added any
      const len = Math.max(prev.length, Math.min(scriptSegments.length, 6));
      const next = [];
      for (let i = 0; i < len; i++) {
        const existing = prev[i];
        if (existing) {
          // Auto-fill prompt only if user hasn't typed
          if (!existing.prompt.trim() && scriptSegments[i]) {
            next.push({ ...existing, prompt: scriptSegments[i].slice(0, 80) });
          } else {
            next.push(existing);
          }
        } else if (scriptSegments[i]) {
          next.push({ prompt: scriptSegments[i].slice(0, 80), pick: null });
        }
      }
      return next.length ? next : [{ prompt: "", pick: null }];
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, scriptSegments.length]);

  // ---- Validation ----
  const canGenerate = useMemo(() => {
    if (!script.trim()) return false;
    if (mode === MODES.AVATAR) {
      return !!avatar && !!voice;
    }
    return !!ttsVoice && scenes.some((s) => s.prompt.trim());
  }, [script, mode, avatar, voice, ttsVoice, scenes]);

  // ---- Generate ----
  const generate = async () => {
    setRenderErr("");
    try {
      const body = {
        mode,
        script,
        aspect,
        captions,
        avatar_id: mode === MODES.AVATAR ? avatar?.id : null,
        voice_id: mode === MODES.AVATAR ? voice?.id : null,
        tts_voice_id: mode === MODES.FACELESS ? ttsVoice?.id : null,
        broll_source: mode === MODES.FACELESS ? brollSource : null,
        scenes: mode === MODES.FACELESS ? scenes.map((s) => ({
          source: s.pick?.source || brollSource,
          prompt: s.prompt,
          video_url: s.pick?.video_url || null,
          thumb: s.pick?.thumb || null,
        })) : [],
      };
      const r = await apiClient.post("/studio/render", body);
      setRender(r.data);
      pollStatus(r.data.id);
    } catch (e) {
      setRenderErr(e?.response?.data?.detail || "Could not start render. Try again.");
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

  // ---- Scene helpers ----
  const updateScene = (idx, patch) => {
    setScenes((s) => s.map((row, i) => i === idx ? { ...row, ...patch } : row));
  };
  const addScene = () => setScenes((s) => [...s, { prompt: "", pick: null }]);
  const removeScene = (idx) => setScenes((s) => s.filter((_, i) => i !== idx));

  // ---- Chip render helpers ----
  const chipAvatar = (
    <button
      className={`chip ${avatar ? "is-set" : ""}`}
      data-testid="chip-avatar"
      onClick={() => setModal("avatar")}
    >
      {avatar?.preview_image_url
        ? <img src={avatar.preview_image_url} alt="" className="chip-thumb" />
        : <span className="chip-icon"><UserCircle2 size={16} /></span>}
      <span className="chip-label">{avatar ? avatar.name : "Avatar"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  const chipVoice = (
    <button
      className={`chip ${voice ? "is-set" : ""}`}
      data-testid="chip-voice"
      onClick={() => setModal("voice")}
    >
      <span className="chip-icon"><Mic size={14} /></span>
      <span className="chip-label">{voice ? `Voice · ${voice.name}` : "Voice"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  const chipTtsVoice = (
    <button
      className={`chip ${ttsVoice ? "is-set" : ""}`}
      data-testid="chip-tts-voice"
      onClick={() => setModal("tts-voice")}
    >
      <span className="chip-icon"><Mic size={14} /></span>
      <span className="chip-label">{ttsVoice ? `Voice · ${ttsVoice.name}` : "Voice"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  const chipAspect = (
    <button className={`chip is-set`} data-testid="chip-aspect" onClick={() => setModal("aspect")}>
      <span className="chip-icon"><Ratio size={14} /></span>
      <span className="chip-label">{aspect === "9_16" ? "9:16 Vertical" : "16:9 Horizontal"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  const chipCaptions = (
    <button className={`chip is-set`} data-testid="chip-captions" onClick={() => setModal("captions")}>
      <span className="chip-icon"><Captions size={14} /></span>
      <span className="chip-label">{captions ? "Captions ON" : "Captions OFF"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  const chipBroll = (
    <button className={`chip is-set`} data-testid="chip-broll" onClick={() => setModal("broll")}>
      <span className="chip-icon"><Film size={14} /></span>
      <span className="chip-label">B-Roll · {brollSource === "ai" ? "AI" : brollSource === "mix" ? "Mix" : brollSource === "pixabay" ? "Library B" : "Library A"}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );

  return (
    <main className="studio-main" data-testid="studio-page">

      {/* Hero */}
      <div className="studio-hero">
        <p className="studio-eyebrow">Studio</p>
        <h1 className="studio-title">Turn your script into a finished video.</h1>
        <p className="studio-sub">
          Paste your script, pick your look in two clicks, and we&rsquo;ll render the final cut — captions, voice, footage and all.
        </p>
      </div>

      {/* Mode toggle */}
      <div className="mode-toggle" role="tablist" data-testid="mode-toggle">
        <button
          role="tab"
          className={`mode-opt ${mode === MODES.AVATAR ? "is-active" : ""}`}
          data-testid="mode-avatar"
          onClick={() => setMode(MODES.AVATAR)}
        >
          <UserCircle2 size={14} /> Avatar
        </button>
        <button
          role="tab"
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
            : "Paste the script for your voiceover. We'll suggest one scene per paragraph."}
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
          <>
            {chipAvatar}
            {chipVoice}
            {chipAspect}
            {chipCaptions}
          </>
        ) : (
          <>
            {chipTtsVoice}
            {chipBroll}
            {chipAspect}
            {chipCaptions}
          </>
        )}
      </div>

      {/* Faceless: scene list */}
      {mode === MODES.FACELESS && (
        <div className="scene-section" data-testid="scene-section">
          <span className="script-label">Scenes</span>
          <div className="scene-list" data-testid="scene-list">
            {scenes.map((s, i) => (
              <div className="scene-card" key={i} data-testid={`scene-card-${i}`}>
                <div className="scene-head">
                  <span className="scene-num">Scene {i + 1}</span>
                  <input
                    className="scene-prompt-input"
                    data-testid={`scene-prompt-${i}`}
                    placeholder="Describe the scene (e.g. 'sunrise over mountains')"
                    value={s.prompt}
                    onChange={(e) => updateScene(i, { prompt: e.target.value })}
                  />
                  {scenes.length > 1 && (
                    <button
                      className="scene-remove"
                      data-testid={`scene-remove-${i}`}
                      onClick={() => removeScene(i)}
                      aria-label="Remove scene"
                    >×</button>
                  )}
                </div>
                <div className="scene-row">
                  {brollSource !== "ai" && (
                    <button
                      className={`scene-pick ${s.pick ? "is-picked" : ""}`}
                      data-testid={`scene-pick-${i}`}
                      onClick={() => setStockModal({ open: true, idx: i })}
                    >
                      {s.pick?.thumb && <img src={s.pick.thumb} alt="" className="scene-pick-thumb" />}
                      {s.pick ? "Replace footage" : "Pick footage"}
                    </button>
                  )}
                  {brollSource === "ai" && (
                    <span className="scene-pick is-picked" data-testid={`scene-ai-${i}`}>AI-generated scene</span>
                  )}
                </div>
              </div>
            ))}
          </div>
          <button className="scene-add" data-testid="scene-add" onClick={addScene}>
            <Plus size={12} style={{ verticalAlign: -2, marginRight: 4 }} /> Add scene
          </button>
        </div>
      )}

      {/* Storyboard (avatar mode shows a single placeholder, faceless shows scenes) */}
      {mode === MODES.FACELESS && scenes.some((s) => s.prompt.trim()) && (
        <div className="storyboard-block" data-testid="storyboard-block">
          <div className="storyboard-head">
            <span className="storyboard-title">Storyboard</span>
          </div>
          <div className="storyboard-strip" data-testid="storyboard-strip">
            {scenes.filter((s) => s.prompt.trim()).map((s, i) => (
              <button
                className="storyboard-card"
                key={i}
                data-testid={`storyboard-card-${i}`}
                onClick={() => setStockModal({ open: true, idx: i })}
              >
                <div className={`storyboard-thumb ${aspect === "16_9" ? "is-16-9" : ""}`}>
                  <span className="storyboard-idx">{i + 1}</span>
                  {s.pick?.thumb && <img src={s.pick.thumb} alt="" />}
                </div>
                <div className="storyboard-meta">
                  <div className="storyboard-prompt">{s.prompt}</div>
                  <div className={`storyboard-status ${s.pick ? "is-ready" : ""}`}>{s.pick ? "Ready" : "Needs footage"}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Generate */}
      <div className="cta-block">
        <button
          className="cta-btn"
          data-testid="generate-btn"
          disabled={!canGenerate || (render && render.status !== "complete" && render.status !== "failed")}
          onClick={generate}
        >
          Render your video
        </button>
        {!canGenerate && (
          <p className="cta-hint" data-testid="cta-hint">
            {!script.trim()
              ? "Paste a script to begin."
              : mode === MODES.AVATAR
                ? !avatar ? "Pick an avatar." : !voice ? "Pick a voice." : ""
                : !ttsVoice ? "Pick a voice." : "Add at least one scene prompt."}
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
            <video
              className="render-video"
              data-testid="render-video"
              src={render.result_url}
              controls
              playsInline
            />
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
      <AvatarPicker
        open={modal === "avatar"}
        onClose={closeModal}
        value={avatar}
        onPick={setAvatar}
      />
      <VoicePicker
        open={modal === "voice"}
        onClose={closeModal}
        value={voice}
        onPick={setVoice}
        source="heygen"
      />
      <VoicePicker
        open={modal === "tts-voice"}
        onClose={closeModal}
        value={ttsVoice}
        onPick={setTtsVoice}
        source="tts"
      />
      <BRollSourcePicker
        open={modal === "broll"}
        onClose={closeModal}
        value={brollSource}
        onPick={setBrollSource}
      />
      <AspectPicker
        open={modal === "aspect"}
        onClose={closeModal}
        value={aspect}
        onPick={setAspect}
      />
      <CaptionsPicker
        open={modal === "captions"}
        onClose={closeModal}
        value={captions}
        onPick={(v) => { captionsTouched.current = true; setCaptions(v); }}
      />
      <StockPicker
        open={stockModal.open}
        sceneIdx={stockModal.idx}
        defaultSource={brollSource === "pixabay" ? "pixabay" : "pexels"}
        query={stockModal.idx >= 0 ? scenes[stockModal.idx]?.prompt : ""}
        aspect={aspect}
        onClose={() => setStockModal({ open: false, idx: -1 })}
        onPick={(r) => {
          if (stockModal.idx >= 0) updateScene(stockModal.idx, { pick: r });
        }}
      />
    </main>
  );
}
