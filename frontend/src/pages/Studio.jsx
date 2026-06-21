import React, { useEffect, useMemo, useRef, useState } from "react";
import { UserCircle2, Mic, Ratio, Film, ChevronDown, Play, Trash2, Sparkles, Wand2, Loader2, RotateCw, Cpu, FolderOpen, Image as ImageIcon, Check } from "lucide-react";
import { apiClient, useAuth } from "../App";
import {
  AvatarPicker,
  VoicePicker,
  BRollSourcePicker,
  AspectPicker,
  StockPicker,
  AIEnginePicker,
} from "../components/Pickers";
import ModePicker, { COMPOSITE_TOAST } from "../components/ModePicker";
import MediaLibrary from "../components/MediaLibrary";
import Toast from "../components/Toast";

const MODES = { AVATAR: "avatar", FACELESS: "faceless" };
const MAX_SCENES = 12;
const SOURCE_HINT = {
  ai:       "An AI-generated visual will be created from your prompt.",
  pexels:   "We'll search the Pexels stock library.",
  pixabay:  "We'll search the Pixabay stock library.",
  uploaded: "We'll use the media file you uploaded for this scene.",
};
const SOURCE_SHORT = { ai: "AI", pexels: "Px", pixabay: "Pb", uploaded: "You" };

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}
const modeChipLabel = (m) => (m === MODES.AVATAR ? "Avatar" : "Faceless");

// Translate raw backend / HeyGen errors into friendly customer-facing copy.
// We surface script-length issues as a script suggestion (no vendor names,
// no cost language).
function friendlyRenderError(e) {
  const raw = (e?.response?.data?.detail || e?.message || "").toString();
  const lower = raw.toLowerCase();
  if (lower.includes("script") && (lower.includes("too long") || lower.includes("character") || lower.includes("length") || lower.includes("limit"))) {
    return "Your script is too long for an avatar video — try shortening it or splitting it into two parts.";
  }
  if (lower.includes("configuration is too large")) {
    return "Render configuration is too large. Please contact support.";
  }
  if (!raw) return "Could not start render. Try again.";
  return raw;
}

const SOURCE_PILL_OPTS = [
  { id: "ai", label: "AI" },
  { id: "pexels", label: "Pexels" },
  { id: "pixabay", label: "Pixabay" },
  { id: "uploaded", label: "Yours" },
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

  // Mode-picker landing card — shown on first visit, persisted to localStorage
  // so returning users skip straight to the chip form. A "Change mode" link
  // re-opens the picker any time. Skipped automatically when a script handoff
  // is in flight (the source mode is already implied by the handoff).
  const [showModePicker, setShowModePicker] = useState(() => {
    try { return !localStorage.getItem("f48_studio_mode_chosen"); }
    catch { return true; }
  });

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

      // Script handoff implies the user already chose a content path on
      // /scripts — skip the mode-picker landing this time and persist the
      // implicit choice so future visits don't re-show it either.
      setShowModePicker(false);
      try { localStorage.setItem("f48_studio_mode_chosen", "1"); } catch {}

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
  // Captions intentionally hidden in this iteration — backend ignores both
  // `captions` and `caption_style`, but we keep the state so the payload
  // contract stays stable for older history docs. Captions UI is reinstated
  // in a future pass once HeyGen + fal pipelines burn them in reliably.
  const captions = false;
  const captionStyle = "boxed";

  // Avatar mode picks
  const [avatar, setAvatar] = useState(null);
  const [voice, setVoice] = useState(null);

  // Faceless mode picks
  const [ttsVoice, setTtsVoice] = useState(null);
  // User-recorded/uploaded voiceover URL (set via the VoiceRecorder inside
  // the TTS Voice picker). When set, backend skips Kokoro TTS entirely
  // and uses this audio file as the voiceover track.
  const [userVoiceoverUrl, setUserVoiceoverUrl] = useState(null);
  const [brollSource, setBrollSource] = useState("pexels"); // global default
  // AI text-to-video engine for AI-sourced scenes. Default "flux" keeps the
  // existing Ken-Burns slideshow behaviour; "kling" / "veo3" / "pika" generate
  // real motion video clips per scene. Only relevant when at least one scene
  // is AI-sourced (broll_source = "ai" or "mix" with AI overrides).
  const [aiEngine, setAiEngine] = useState("flux");
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
  // Separate ref for the background history-list poll so it can run while
  // pollRef is focused on the latest in-flight render.
  const historyPollRef = useRef(null);

  // Auth context (kept for entitlement gating elsewhere, not for render gating).
  const { user } = useAuth();
  const isAdmin = !!user?.isAdmin;
  const [toast, setToast] = useState("");
  // History "play" opens an inline modal. Opening the raw HeyGen/fal CDN
  // URL in a new tab shows a blank file2.heygen.ai page (signed URL + the
  // browser can't render the bare MP4 inline). Keeping playback in-app.
  const [playerModal, setPlayerModal] = useState(null);  // {url, aspect} | null
  // Per-row selection for bulk-delete in the Recent renders list.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const toggleSelected = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const clearSelected = () => setSelectedIds(new Set());
  const selectAllVisible = (rows) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const isAdminLocal = !!user?.isAdmin;
      for (const r of rows) {
        if (isAdminLocal || r.status === "complete" || r.status === "failed") next.add(r.id);
      }
      return next;
    });
  };
  const bulkDelete = async () => {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    try {
      const r = await apiClient.post("/studio/render/bulk-delete", { ids });
      setHistory((h) => h.filter((row) => !selectedIds.has(row.id)));
      clearSelected();
      setToast(`Deleted ${r.data.deleted} render${r.data.deleted === 1 ? "" : "s"}.`);
    } catch (e) {
      setRenderErr(e?.response?.data?.detail || "Bulk delete failed.");
    }
  };

  // Scrolls the active render-card into view + briefly highlights so admin
  // notices when a render kicks off — fixes the "I clicked but nothing
  // happened" footgun where the render-card is above the user's current
  // scroll position (common when re-firing from a history row).
  const scrollToRenderCard = () => {
    setTimeout(() => {
      document.querySelector('[data-testid="render-card"]')?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 100);
  };

  // Modal state
  const [modal, setModal] = useState(null);
  const [stockModal, setStockModal] = useState({ open: false, idx: -1 });
  // Media library modal — opens scoped to a particular scene index when
  // the user clicks "Open library" on an "uploaded" source scene. idx -1
  // means just show the library without picking (no scene context).
  const [libraryModal, setLibraryModal] = useState({ open: false, idx: -1 });
  // 3-thumbnail-per-scene candidates. Map of scene-idx → [{thumb, video_url, source, duration}].
  // Populated by clicking "Preview clips" — fans out to /api/studio/stock-candidates,
  // grouped by source so each external API call is dense. Cleared whenever
  // scenes are regenerated.
  const [sceneCandidates, setSceneCandidates] = useState({});
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [candidatesErr, setCandidatesErr] = useState("");

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneLines.length]);

  // Most-recently-generated per-scene weight (word count from the script
  // sentence each prompt covers). Captured when "Generate from script" runs.
  // Used to allocate proportional video duration per scene so cuts land on
  // natural pauses. Reset to all-1s if the user manually edits scene count.
  const autoWeightsRef = useRef([]);
  const autoPromptsRef = useRef([]);

  // The fully-resolved scenes (line + effective source + pick + weight)
  const scenes = useMemo(() => {
    // Only use stored weights when the current prompt list matches what the
    // auto-generator produced (same length AND same contents — if the user
    // edited any line the mapping is no longer safe).
    const stored = autoPromptsRef.current;
    const weightsAlign =
      stored.length === sceneLines.length &&
      stored.every((p, i) => p === sceneLines[i]);
    return sceneLines.map((prompt, i) => {
      const ov = sceneOverrides[i] || {};
      const effective = ov.source ?? (brollSource === "mix" ? null : brollSource);
      const weight = weightsAlign ? autoWeightsRef.current[i] : null;
      return {
        prompt,
        source: effective,
        pick: ov.pick || null,
        ...(weight ? { weight } : {}),
      };
    });
  }, [sceneLines, sceneOverrides, brollSource]);

  // ---- Load history on mount + background poll while any in-flight ----
  // Background poll lets the user fire multiple renders concurrently:
  // the active render-card focuses the latest one, while previous in-flight
  // renders continue to update their progress in the history list.
  useEffect(() => {
    loadHistory();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (historyPollRef.current) clearInterval(historyPollRef.current);
    };
  }, []);

  // Background history poll — kicks in whenever ANY history row is in-flight
  // (not "complete" / "failed"). Re-fetches the whole list every 3s.
  useEffect(() => {
    const anyInFlight = history.some(
      (r) => r.status && r.status !== "complete" && r.status !== "failed"
    );
    if (!anyInFlight) {
      if (historyPollRef.current) {
        clearInterval(historyPollRef.current);
        historyPollRef.current = null;
      }
      return;
    }
    if (historyPollRef.current) return;  // already polling
    historyPollRef.current = setInterval(() => {
      loadHistory();
    }, 3000);
    return () => {
      if (historyPollRef.current) {
        clearInterval(historyPollRef.current);
        historyPollRef.current = null;
      }
    };
  }, [history]);

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
    // Faceless: need a voice (TTS or user-recorded) AND scenes with valid sources.
    if (!ttsVoice && !userVoiceoverUrl) return false;
    if (scenes.length === 0) return false;
    // Every scene needs a resolved source (mix mode requires explicit pick per scene)
    if (scenes.some((s) => !s.source)) return false;
    // Uploaded scenes need a pre-picked media file (no auto-search fallback).
    if (scenes.some((s) => s.source === "uploaded" && !s.pick?.video_url)) return false;
    return true;
  }, [script, mode, avatar, voice, ttsVoice, userVoiceoverUrl, scenes]);

  // Build a payload from the current form state. Reused by the live cost
  // estimate request and the actual /studio/render request below.
  const buildPayload = () => ({
    mode,
    script,
    aspect,
    captions,
    caption_style: captionStyle,
    avatar_id: mode === MODES.AVATAR ? avatar?.id : null,
    voice_id: mode === MODES.AVATAR ? voice?.id : null,
    tts_voice_id: mode === MODES.FACELESS ? ttsVoice?.id : null,
    user_voiceover_url: mode === MODES.FACELESS ? userVoiceoverUrl : null,
    broll_source: mode === MODES.FACELESS ? brollSource : null,
    ai_engine: mode === MODES.FACELESS ? aiEngine : "flux",
    scenes: mode === MODES.FACELESS ? scenes.map((s) => ({
      source: s.source,
      prompt: s.prompt,
      video_url: s.pick?.video_url || null,
      thumb: s.pick?.thumb || null,
      // Weight = word count of the script sentence this scene covers.
      // Backend uses it for proportional per-scene duration so cuts land on
      // natural voiceover pauses. Omitted when scenes were hand-edited.
      ...(s.weight ? { weight: s.weight } : {}),
    })) : [],
  });

  // ---- Generate ----
  // Production behavior: every render is real. No dry-run, no admin gate,
  // no confirm modal. The backend's silent circuit-breaker rejects only
  // pathological payloads; everything else fires the real pipeline.
  const fireRender = async (body) => {
    setRenderErr("");
    try {
      const r = await apiClient.post("/studio/render", body);
      setRender(r.data);
      setToast("Render started…");
      scrollToRenderCard();
      pollStatus(r.data.id);
    } catch (e) {
      setRenderErr(friendlyRenderError(e));
    }
  };

  const generate = () => fireRender(buildPayload());

  // "Render both aspects" — fire two renders in parallel (9:16 + 16:9) using
  // the same script, avatar/voice, scenes, and AI engine. The active-renders
  // grid above the History list will show both progress bars side by side.
  const renderBothAspects = async () => {
    setRenderErr("");
    try {
      const r = await apiClient.post("/studio/render/both-aspects", buildPayload());
      const jobs = r.data?.jobs || [];
      if (jobs.length === 0) throw new Error("Empty response");
      // Set the freshly-submitted 9:16 as the focused render (first in the
      // returned array). The 16:9 will show up in the active-grid via the
      // history polling loop.
      const focus = jobs[0];
      setRender(focus);
      // Insert both job docs at the top of history immediately so the user
      // sees both progress cards without waiting for the next history poll.
      setHistory((h) => {
        const ids = new Set(jobs.map((j) => j.id));
        return [...jobs, ...h.filter((row) => !ids.has(row.id))];
      });
      setToast(`Two renders queued — 9:16 + 16:9.`);
      scrollToRenderCard();
      pollStatus(focus.id);
    } catch (e) {
      setRenderErr(friendlyRenderError(e));
    }
  };

  // Re-fire the SAME render payload (same script, avatar, voice, scenes).
  // Smoother UX than rebuilding the form when iterating on a render.
  const regenerate = async (sourceDoc) => {
    if (!sourceDoc) return;
    setRenderErr("");
    // Visual reset so the click registers immediately.
    setRender({
      ...sourceDoc,
      id: null,
      status: "queued",
      progress: 0,
      progress_label: "Regenerating…",
      result_url: null,
      error: null,
    });
    const body = {
      mode: sourceDoc.mode,
      script: sourceDoc.script,
      aspect: sourceDoc.aspect,
      captions: sourceDoc.captions,
      caption_style: sourceDoc.caption_style,
      avatar_id: sourceDoc.avatar_id,
      voice_id: sourceDoc.voice_id,
      tts_voice_id: sourceDoc.tts_voice_id,
      broll_source: sourceDoc.broll_source,
      scenes: sourceDoc.scenes || [],
      broll_cutaway_interval_s: sourceDoc.broll_cutaway_interval_s ?? 12,
    };
    try {
      const r = await apiClient.post("/studio/render", body);
      setRender(r.data);
      setToast("Regenerating — scroll up to watch.");
      scrollToRenderCard();
      pollStatus(r.data.id);
    } catch (e) {
      setRenderErr(friendlyRenderError(e));
    }
  };

  const pollStatus = (jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    // Tolerate transient errors (network blips, token-refresh races) — only
    // give up after MAX_FAIL consecutive failures. Previously a single 5xx
    // killed the poll loop entirely, which is why a long-running real
    // render would silently "freeze" on the UI side at 85%.
    let consecutiveFailures = 0;
    const MAX_FAIL = 6;  // ~9 seconds of failures at 1.5s interval
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiClient.get(`/studio/render/${jobId}`);
        consecutiveFailures = 0;
        // Race guard: when user fires a new render mid-flight, the active
        // render-card is now pointing at the newer job. Don't stomp it with
        // updates from the older poll — just refresh history (which carries
        // the older job's progress in its row) and let this poll exit.
        setRender((current) => {
          if (current && current.id !== jobId) {
            return current;  // active card belongs to a newer render
          }
          return r.data;
        });
        if (r.data.status === "complete" || r.data.status === "failed") {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadHistory();
        }
      } catch {
        consecutiveFailures += 1;
        if (consecutiveFailures >= MAX_FAIL) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setRenderErr("Lost connection to render — refresh the page and click Resume on the row to keep tracking it.");
        }
      }
    }, 1500);
  };

  // Resume polling on a render that's still in progress (e.g. user refreshed
  // the page mid-render or our polling timed out due to a network blip).
  // Loads the latest doc into the active render-card and re-attaches the
  // poll loop so the user can watch it finish.
  const resumeRender = async (jobId) => {
    try {
      const r = await apiClient.get(`/studio/render/${jobId}`);
      setRender(r.data);
      setToast("Resumed tracking — watch progress above.");
      scrollToRenderCard();
      if (r.data.status !== "complete" && r.data.status !== "failed") {
        pollStatus(jobId);
      }
    } catch (e) {
      setRenderErr(e?.response?.data?.detail || "Could not resume — render may have been deleted.");
    }
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
  // Backend splits the script into natural sentence beats first (3-12 of
  // them), then asks Claude for exactly one prompt per beat. We store the
  // per-scene weight (= word count of each beat) so the render pipeline can
  // give each scene a duration PROPORTIONAL to its sentence length —
  // visuals change exactly when the voiceover pauses.
  const generatePromptsFromScript = async () => {
    if (!script.trim()) return;
    setPromptsErr("");
    setGeneratingPrompts(true);
    try {
      const r = await apiClient.post("/studio/broll-prompts", { script });
      const sceneObjs = (r.data.scenes || []).slice(0, 12);
      const lines = sceneObjs.map((s) => s.prompt);
      const weights = sceneObjs.map((s) => s.weight || 1);
      setBulkPrompts(lines.join("\n"));
      setSceneOverrides(lines.map(() => ({})));
      autoPromptsRef.current = lines;
      autoWeightsRef.current = weights;
      // Stale candidates from the previous script are no longer relevant —
      // the prompt → thumbnail mapping is positional.
      setSceneCandidates({});
      setCandidatesErr("");
    } catch (e) {
      setPromptsErr(e?.response?.data?.detail || "Could not generate prompts. Try again.");
    } finally {
      setGeneratingPrompts(false);
    }
  };

  // Fetch 3 candidate clips per scene from Pexels/Pixabay. We split the
  // scene list into one bundle per source (Pexels-batch + Pixabay-batch)
  // so the backend's fan-out hits each provider once with all queries in
  // parallel — that's ~2s end-to-end for the typical 5-7 scene case vs
  // 12+ seconds if we called once per scene.
  const fetchCandidates = async () => {
    // Only scenes whose source is pexels/pixabay AND have a prompt.
    const eligible = scenes
      .map((s, i) => ({ s, i }))
      .filter(({ s }) => (s.source === "pexels" || s.source === "pixabay") && s.prompt);
    if (eligible.length === 0) {
      setCandidatesErr("No Pexels/Pixabay scenes to preview. Set a stock source on at least one scene first.");
      return;
    }
    setCandidatesErr("");
    setLoadingCandidates(true);
    try {
      const orientation = aspect === "9_16" ? "portrait" : "landscape";
      const groups = {
        pexels: eligible.filter(({ s }) => s.source === "pexels"),
        pixabay: eligible.filter(({ s }) => s.source === "pixabay"),
      };
      const reqs = [];
      for (const src of ["pexels", "pixabay"]) {
        if (groups[src].length === 0) continue;
        reqs.push(
          apiClient.post("/studio/stock-candidates", {
            prompts: groups[src].map(({ s }) => s.prompt),
            source: src,
            orientation,
          }).then((r) => ({ src, payload: r.data.candidates || [], group: groups[src] }))
        );
      }
      const results = await Promise.all(reqs);
      const merged = {};
      for (const { payload, group } of results) {
        // Backend returns candidates in the same order we sent prompts, with
        // {idx, prompt, candidates}. Remap each row back to the original
        // scene index using the group order we preserved.
        payload.forEach((row) => {
          const sceneIdx = group[row.idx]?.i;
          if (sceneIdx !== undefined && row.candidates) {
            merged[sceneIdx] = row.candidates;
          }
        });
      }
      setSceneCandidates(merged);
      if (Object.keys(merged).length === 0) {
        setCandidatesErr("No candidates returned. Try simpler prompts or a different stock source.");
      }
    } catch (e) {
      setCandidatesErr(e?.response?.data?.detail || "Could not load candidates. Try again.");
    } finally {
      setLoadingCandidates(false);
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
    <button className={`chip ${(ttsVoice || userVoiceoverUrl) ? "is-set" : ""}`} data-testid="chip-tts-voice" onClick={() => setModal("tts-voice")}>
      <span className="chip-icon"><Mic size={14} /></span>
      <span className="chip-label">
        {userVoiceoverUrl ? "Voice · Your recording" : (ttsVoice ? `Voice · ${ttsVoice.name}` : "Voice")}
      </span>
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
  const brollChipLabel = {
    ai: "B-Roll · AI",
    pexels: "B-Roll · Pexels",
    pixabay: "B-Roll · Pixabay",
    uploaded: "B-Roll · Yours",
    mix: "B-Roll · Mix",
  }[brollSource] || "B-Roll";
  const chipBroll = (
    <button className="chip is-set" data-testid="chip-broll" onClick={() => setModal("broll")}>
      <span className="chip-icon"><Film size={14} /></span>
      <span className="chip-label">{brollChipLabel}</span>
      <ChevronDown size={14} className="chip-caret" />
    </button>
  );
  // AI engine chip — always visible in Faceless mode so users can discover
  // and configure the engine BEFORE picking an AI b-roll source. Earlier iter
  // hid it unless broll_source = "ai" or "mix" but that buried the feature.
  // The picker explains that the choice only applies to AI scenes; pure stock
  // renders will simply ignore the setting.
  const aiEngineLabel = {
    flux: "Engine · Flux + Motion",
    kling: "Engine · Kling 2.1",
    veo3: "Engine · Veo 3.1",
    pika: "Engine · Pika 2.1",
  }[aiEngine] || "AI Engine";
  const chipAiEngine = (
    <button className="chip is-set" data-testid="chip-ai-engine" onClick={() => setModal("ai-engine")}>
      <span className="chip-icon"><Cpu size={14} /></span>
      <span className="chip-label">{aiEngineLabel}</span>
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

      {/* First-visit landing card — full-bleed mode picker. Once the user
          selects Avatar or Faceless we hide this and surface the chip form
          underneath; a small "Change mode" link in the mode-toggle row lets
          them reopen it later. Composite is a Phase 3 preview right now. */}
      {showModePicker ? (
        <ModePicker
          onPick={(picked) => {
            setMode(picked === "avatar" ? MODES.AVATAR : MODES.FACELESS);
            setShowModePicker(false);
            try { localStorage.setItem("f48_studio_mode_chosen", "1"); } catch {}
          }}
          onComingSoon={() => setToast(COMPOSITE_TOAST)}
        />
      ) : (
        <>
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
          {/* Slim affordance to re-open the landing picker — useful for
              users who want to A/B between modes without losing the
              concept of a deliberate mode selection. */}
          <button
            type="button"
            className="mode-toggle-change"
            data-testid="mode-toggle-change"
            onClick={() => setShowModePicker(true)}
          >
            ← Change mode
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
          <>{chipAvatar}{chipVoice}{chipAspect}</>
        ) : (
          <>{chipTtsVoice}{chipBroll}{chipAiEngine}{chipAspect}</>
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
              <button
                type="button"
                className="generate-prompts-btn is-secondary"
                data-testid="fetch-candidates-btn"
                disabled={loadingCandidates || scenes.length === 0}
                onClick={fetchCandidates}
                title={scenes.length === 0 ? "Generate prompts first" : "Preview 3 thumbnail candidates per stock scene"}
              >
                {loadingCandidates ? <Loader2 size={12} className="spin" /> : <ImageIcon size={12} />}
                {loadingCandidates ? "Loading…" : "Preview clips"}
              </button>
              <span className="scene-section-count" data-testid="scene-count">
                <strong>{sceneLines.length}</strong> {sceneLines.length === 1 ? "scene" : "scenes"}
                {scenes.length > 0 && scenes.every((s) => s.weight)
                  ? " · auto-paced from script"
                  : ` · up to ${MAX_SCENES}`}
              </span>
            </div>
          </div>
          {promptsErr && <p className="cta-error" data-testid="prompts-err">{promptsErr}</p>}
          {candidatesErr && <p className="cta-error" data-testid="candidates-err">{candidatesErr}</p>}
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
                        {s.source === "uploaded" && <FolderOpen size={12} />}
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
                        {s.source === "uploaded" && (
                          <button
                            type="button"
                            className="scene-hint-pick"
                            data-testid={`scene-library-${i}`}
                            onClick={() => setLibraryModal({ open: true, idx: i })}
                          >
                            {s.pick?.video_url ? (
                              <>
                                {s.pick.thumb && <img src={s.pick.thumb} alt="" className="scene-hint-thumb" style={{ verticalAlign: -6, marginRight: 6 }} />}
                                Change file
                              </>
                            ) : "Pick from your library"}
                          </button>
                        )}
                      </>
                    ) : (
                      <span style={{ color: "var(--warning)" }}>Pick a source for this scene.</span>
                    )}
                  </div>
                  {sceneCandidates[i] && sceneCandidates[i].length > 0 && (
                    <div
                      className="scene-candidates"
                      data-testid={`scene-candidates-${i}`}
                      role="radiogroup"
                      aria-label={`Choose a clip for scene ${i + 1}`}
                    >
                      {sceneCandidates[i].slice(0, 3).map((c) => {
                        const isPicked = s.pick?.video_url === c.video_url;
                        return (
                          <button
                            type="button"
                            key={c.id}
                            role="radio"
                            aria-checked={isPicked}
                            className={`scene-candidate ${isPicked ? "is-picked" : ""}`}
                            data-testid={`scene-candidate-${i}-${c.id}`}
                            onClick={() => setScenePick(i, c)}
                            title={isPicked ? "Currently picked" : "Use this clip"}
                          >
                            <div className={`scene-candidate-thumb ${aspect === "16_9" ? "is-landscape" : ""}`}>
                              {c.thumb ? (
                                <img src={c.thumb} alt="" loading="lazy" />
                              ) : (
                                <div className="scene-candidate-noimg"><Film size={20} /></div>
                              )}
                              <span className="scene-candidate-src">{c.source === "pexels" ? "Pexels" : "Pixabay"}</span>
                              {isPicked && (
                                <span className="scene-candidate-check"><Check size={14} /></span>
                              )}
                              {c.duration ? (
                                <span className="scene-candidate-dur">{Math.round(c.duration)}s</span>
                              ) : null}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
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
                  else if (s.source === "uploaded") setLibraryModal({ open: true, idx: i });
                }}
              >
                <div className={`storyboard-thumb ${aspect === "16_9" ? "is-16-9" : ""}`}>
                  <span className="storyboard-idx">{i + 1}</span>
                  {s.source && (
                    <span className="storyboard-source-badge" data-source={s.source}>
                      {SOURCE_SHORT[s.source]}
                    </span>
                  )}
                  {s.pick?.thumb ? (
                    <img src={s.pick.thumb} alt="" />
                  ) : (
                    <div className="storyboard-thumb-placeholder" data-source={s.source || "none"} aria-hidden="true">
                      {s.source === "ai" ? (
                        <>
                          <Sparkles size={22} />
                          <span className="storyboard-thumb-engine">AI visual</span>
                        </>
                      ) : s.source === "pexels" || s.source === "pixabay" ? (
                        <>
                          <Film size={22} />
                          <span className="storyboard-thumb-engine">{s.source === "pexels" ? "Pexels search" : "Pixabay search"}</span>
                        </>
                      ) : s.source === "uploaded" ? (
                        <>
                          <FolderOpen size={22} />
                          <span className="storyboard-thumb-engine">Your media</span>
                        </>
                      ) : (
                        <span className="storyboard-thumb-engine">No source</span>
                      )}
                    </div>
                  )}
                </div>
                <div className="storyboard-meta">
                  <div className="storyboard-prompt">{s.prompt}</div>
                  <div className={`storyboard-status ${s.pick || s.source === "ai" ? "is-ready" : ""}`}>
                    {!s.source ? "Pick source"
                      : s.source === "ai" ? "AI scene"
                      : s.source === "uploaded" ? (s.pick ? "Your file ready" : "Pick a file")
                      : (s.pick ? "Clip ready" : "Auto search")}
                  </div>
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
          disabled={!canGenerate}
          onClick={generate}
        >
          Render your video
        </button>
        <button
          type="button"
          className="cta-btn-secondary"
          data-testid="generate-both-aspects-btn"
          disabled={!canGenerate}
          onClick={renderBothAspects}
          title="Queue two parallel renders — one 9:16 and one 16:9 — with the same script and settings."
        >
          <Ratio size={14} /> Render both aspects (9:16 + 16:9)
        </button>
        {!canGenerate && (
          <p className="cta-hint" data-testid="cta-hint">
            {!script.trim()
              ? "Paste a script to begin."
              : mode === MODES.AVATAR
                ? !avatar ? "Pick an avatar." : !voice ? "Pick a voice." : ""
                : (!ttsVoice && !userVoiceoverUrl) ? "Pick a voice or record your own."
                  : scenes.length === 0 ? "Add at least one B-roll prompt."
                    : scenes.some((s) => s.source === "uploaded" && !s.pick?.video_url) ? "Pick a media file for each 'Yours' scene."
                      : "Pick a source for every scene."}
          </p>
        )}
        {render && render.status !== "complete" && render.status !== "failed" && canGenerate && (
          <p className="cta-hint" data-testid="cta-concurrent-hint">
            Tip: you can queue another render now — your current one keeps running in History.
          </p>
        )}
        {renderErr && <p className="cta-error" data-testid="cta-error">{renderErr}</p>}
      </div>

      {/* Active renders — shows every in-flight render so concurrent
          renders (e.g. a 9:16 fired right after a 16:9) are both visible
          at the same time. The most-recently-completed render shows below
          this grid so you can play it without scrolling to History. */}
      {(() => {
        // Combine the freshly-submitted `render` with any other in-flight
        // history rows. De-dupe by id (render is also in history).
        const inflightFromHistory = history.filter(
          (h) => h.status !== "complete" && h.status !== "failed"
        );
        const activeMap = new Map();
        if (render && render.status !== "complete" && render.status !== "failed") {
          activeMap.set(render.id, render);
        }
        for (const r of inflightFromHistory) {
          if (!activeMap.has(r.id)) activeMap.set(r.id, r);
        }
        const activeList = Array.from(activeMap.values());
        const terminalCurrent =
          render && (render.status === "complete" || render.status === "failed")
            ? render
            : null;
        return (
          <>
            {activeList.length > 0 && (
              <div
                className={`active-grid is-${Math.min(activeList.length, 3)}`}
                data-testid="active-render-grid"
              >
                {activeList.map((r) => (
                  <div
                    key={r.id}
                    className="render-card is-mini"
                    data-testid={`active-card-${r.id}`}
                  >
                    <div
                      className={`render-skeleton ${
                        r.aspect === "9_16" ? "is-portrait" : "is-landscape"
                      }`}
                    >
                      <div className="render-skeleton-stripes" aria-hidden="true" />
                      <div className="render-skeleton-glow" aria-hidden="true" />
                      <div className="render-skeleton-center">
                        <div className="render-skeleton-play" aria-hidden="true">
                          <Play size={28} />
                        </div>
                        <div className="render-skeleton-label">
                          {r.progress_label || "Building your video…"}
                        </div>
                        <div className="render-skeleton-pct">{r.progress}%</div>
                      </div>
                    </div>
                    <div className="render-status">
                      <span className="render-status-label">
                        {r.mode === MODES.AVATAR ? "Avatar" : "Faceless"} ·{" "}
                        {r.aspect === "9_16" ? "9:16" : "16:9"}
                      </span>
                      <span className="render-status-pct">{r.progress}%</span>
                    </div>
                    <div className="render-bar">
                      <div
                        className="render-bar-fill is-progressing"
                        style={{ width: `${r.progress}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
            {terminalCurrent && (
              <div className="render-card" data-testid="render-card">
                <div className="render-status">
                  <span className="render-status-label" data-testid="render-status-label">
                    {terminalCurrent.progress_label || terminalCurrent.status}
                  </span>
                  <span className="render-status-pct" data-testid="render-progress">
                    {terminalCurrent.progress}%
                  </span>
                </div>
                <div className="render-bar">
                  <div
                    className="render-bar-fill"
                    style={{ width: `${terminalCurrent.progress}%` }}
                  />
                </div>
                {terminalCurrent.status === "complete" && terminalCurrent.result_url && (
                  <video
                    className={`render-video ${terminalCurrent.aspect === "9_16" ? "is-portrait" : ""}`}
                    data-testid="render-video"
                    src={terminalCurrent.result_url}
                    controls
                    playsInline
                  />
                )}
                {terminalCurrent.status === "failed" && (
                  <p style={{ color: "var(--danger)", margin: 0 }}>
                    Render failed:{" "}
                    {friendlyRenderError({
                      response: { data: { detail: terminalCurrent.error } },
                    })}
                  </p>
                )}
                <button
                  type="button"
                  className="header-btn"
                  data-testid="render-card-regenerate"
                  onClick={() => regenerate(terminalCurrent)}
                  style={{ alignSelf: "flex-start" }}
                >
                  <RotateCw size={13} /> Regenerate
                </button>
              </div>
            )}
          </>
        );
      })()}

      {/* History */}
      <div className="history-block" data-testid="history-block">
        <div className="history-head">
          <span>Recent renders</span>
          {history.length > 0 && (
            <div className="history-head-actions">
              <button
                type="button"
                className="header-btn"
                data-testid="history-select-all"
                onClick={() => selectAllVisible(history)}
              >
                Select all
              </button>
              {selectedIds.size > 0 && (
                <>
                  <button
                    type="button"
                    className="header-btn"
                    data-testid="history-clear-selection"
                    onClick={clearSelected}
                  >
                    Clear ({selectedIds.size})
                  </button>
                  <button
                    type="button"
                    className="header-btn is-danger"
                    data-testid="history-bulk-delete"
                    onClick={bulkDelete}
                  >
                    <Trash2 size={13} /> Delete {selectedIds.size} selected
                  </button>
                </>
              )}
            </div>
          )}
        </div>
        {history.length === 0 ? (
          <div className="history-empty" data-testid="history-empty">No renders yet. Your finished videos will appear here.</div>
        ) : (
          <div className="history-list">
            {history.map((r) => {
              // Admin can force-delete any status (covers stuck orphans).
              // Customers can only act on completed/failed rows.
              const terminal = r.status === "complete" || r.status === "failed";
              const selectable = isAdmin || terminal;
              const isChecked = selectedIds.has(r.id);
              return (
              <div
                className={`history-row ${isChecked ? "is-selected" : ""}`}
                key={r.id}
                data-testid={`history-row-${r.id}`}
              >
                <label
                  className="history-check"
                  data-testid={`history-check-${r.id}`}
                  aria-label="Select render"
                  style={{ visibility: selectable ? "visible" : "hidden" }}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={!selectable}
                    onChange={() => toggleSelected(r.id)}
                  />
                </label>
                <div className="history-meta">
                  <span className={`history-chip is-${r.mode}`}>{modeChipLabel(r.mode)}</span>
                  <span className={`history-chip is-${r.status === "complete" ? "complete" : r.status === "failed" ? "failed" : "progress"}`}>
                    {r.status}
                  </span>
                  <span className="history-date">{fmtDate(r.created_at)}</span>
                </div>
                {!terminal && (
                  <div className="history-row-progress" data-testid={`history-progress-${r.id}`}>
                    <div className="history-row-progress-meta">
                      <span className="history-row-progress-label">{r.progress_label || "Working…"}</span>
                      <span className="history-row-progress-pct">{r.progress ?? 0}%</span>
                    </div>
                    <div className="history-row-bar">
                      <div
                        className="history-row-bar-fill is-progressing"
                        style={{ width: `${r.progress ?? 0}%` }}
                      />
                    </div>
                  </div>
                )}
                <div className="history-actions">
                  {!terminal && (
                    <button
                      className="icon-btn"
                      data-testid={`history-resume-${r.id}`}
                      onClick={() => resumeRender(r.id)}
                      aria-label="Resume tracking"
                      title="Resume tracking this render"
                    >
                      <Play size={14} />
                    </button>
                  )}
                  {r.status === "complete" && r.result_url && (
                    <button
                      className="icon-btn"
                      onClick={() => setPlayerModal({ url: r.result_url, aspect: r.aspect })}
                      data-testid={`history-play-${r.id}`}
                      aria-label="Play"
                      title="Play"
                    >
                      <Play size={14} />
                    </button>
                  )}
                  {(r.status === "complete" || r.status === "failed") && (
                    <button
                      className="icon-btn"
                      data-testid={`history-regenerate-${r.id}`}
                      onClick={async () => {
                        try {
                          const full = await apiClient.get(`/studio/render/${r.id}`);
                          regenerate(full.data);
                        } catch (e) {
                          setRenderErr(friendlyRenderError(e));
                        }
                      }}
                      aria-label="Regenerate"
                      title="Regenerate with same settings"
                    >
                      <RotateCw size={14} />
                    </button>
                  )}
                  <button
                    className="icon-btn is-danger"
                    data-testid={`history-delete-${r.id}`}
                    onClick={() => deleteRender(r.id)}
                    disabled={!isAdmin && !terminal}
                    aria-label="Delete"
                    title={!terminal && isAdmin ? "Force-delete stuck render" : "Delete"}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              );
            })}
          </div>
        )}
      </div>
      </>
      )}

      {/* Modals */}
      <AvatarPicker open={modal === "avatar"} onClose={closeModal} value={avatar} onPick={setAvatar} currentAspect={aspect} />
      <VoicePicker open={modal === "voice"} onClose={closeModal} value={voice} onPick={setVoice} source="heygen" />
      <VoicePicker
        open={modal === "tts-voice"}
        onClose={closeModal}
        value={ttsVoice}
        onPick={setTtsVoice}
        source="tts"
        userVoiceoverUrl={userVoiceoverUrl}
        onUserVoiceoverChange={(url) => {
          setUserVoiceoverUrl(url);
          // Clearing AI TTS pick when the user records their own voice keeps
          // the chip UI honest. Backend prefers user_voiceover_url regardless.
          if (url) setTtsVoice(null);
        }}
      />
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
      <AIEnginePicker
        open={modal === "ai-engine"}
        onClose={closeModal}
        value={aiEngine}
        onPick={setAiEngine}
        isAdmin={isAdmin}
      />
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

      <MediaLibrary
        open={libraryModal.open}
        sceneIdx={libraryModal.idx}
        aspect={aspect}
        onClose={() => setLibraryModal({ open: false, idx: -1 })}
        onPick={(item) => {
          if (libraryModal.idx >= 0) setScenePick(libraryModal.idx, item);
        }}
      />

      {/* Inline player modal — replaces the broken "open URL in new tab" path. */}
      {playerModal && (
        <div
          className="player-modal-backdrop"
          data-testid="player-modal-backdrop"
          onClick={() => setPlayerModal(null)}
        >
          <div
            className={`player-modal ${playerModal.aspect === "9_16" ? "is-portrait" : "is-landscape"}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="player-modal-close"
              data-testid="player-modal-close"
              onClick={() => setPlayerModal(null)}
              aria-label="Close"
            >
              ×
            </button>
            <video
              data-testid="player-modal-video"
              src={playerModal.url}
              controls
              autoPlay
              playsInline
            />
          </div>
        </div>
      )}

      <Toast message={toast} onDismiss={() => setToast("")} />
    </main>
  );
}
