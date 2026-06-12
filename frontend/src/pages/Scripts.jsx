import React, { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Trash2, Sparkles, FileText, Smartphone, Repeat, Loader2, Bookmark, BookmarkCheck, ChevronRight, ArrowLeft, ClipboardCopy } from "lucide-react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiClient, useAuth } from "../App";
import {
  parseSections,
  LONG_SECTION_ORDER,
  SHORTS_SECTION_ORDER,
  extractNarration,
  extractBrollPrompts,
} from "../utils/parser";
import PhoneFrame from "../components/PhoneFrame";
import Toast from "../components/Toast";

const MODES = { LONG: "long", SHORTS: "shorts" };
const STEPS = { TOPIC: "topic", ANGLES: "angles", GENERATING: "generating", RESULT: "result" };

const LENGTHS = [
  { id: "short",  label: "Short", desc: "5–8 min · 800–1,200 words" },
  { id: "medium", label: "Medium", desc: "10–15 min · 1,500–2,200 words" },
  { id: "long",   label: "Long", desc: "18–25 min · 2,700–3,800 words" },
];
const PLATFORMS = [
  { id: "youtube", label: "YouTube Shorts", accent: "#FF0033" },
  { id: "reels",   label: "Instagram Reels", accent: "#E1306C" },
  { id: "tiktok",  label: "TikTok", accent: "#25F4EE" },
];

const SECTION_LABEL = {
  angles: "Topic Angles", concept: "Video Concept", hooks: "Hook Variations",
  outline: "Outline", script: "Narration Script", transitions: "Transitions",
  broll: "B-Roll Shot List", notes: "Production Notes",
  shortScript: "Short-Form Script", onScreen: "On-Screen Text",
  caption: "Caption", hashtags: "Hashtags",
  titleVariants: "Title / Thumbnail Variants", coverPrompts: "Cover Image Prompts",
};

const TAGLINES = [
  "Write a script that gets watched.",
  "Type a topic. Get a complete script.",
  "From blank page to ready-to-record — in seconds.",
];

const ANGLE_CAT = {
  curiosity:  { label: "Curiosity", color: "var(--cat-curiosity)" },
  contrarian: { label: "Contrarian", color: "var(--cat-contrarian)" },
  "how-to":   { label: "How-To", color: "var(--cat-howto)" },
  story:      { label: "Story", color: "var(--cat-story)" },
  list:       { label: "List", color: "var(--cat-list)" },
};

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}

function CopyButton({ text, testid }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-btn"
      data-testid={testid}
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {}
      }}
    >
      <Copy size={12} /> {copied ? "Copied!" : "Copy"}
    </button>
  );
}

function SectionCard({ keyName, section, testid }) {
  if (!section) return null;
  return (
    <section className="section-card" data-testid={testid}>
      <header className="section-card-head">
        <h3 className="section-card-title">{SECTION_LABEL[keyName] || section.title}</h3>
        <CopyButton text={section.body} testid={`${testid}-copy`} />
      </header>
      <div className="section-card-body markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
      </div>
    </section>
  );
}

function SkeletonCard({ keyName }) {
  return (
    <section className="section-card section-card-skeleton" data-testid={`skeleton-${keyName}`} aria-hidden="true">
      <header className="section-card-head">
        <div className="skeleton-bar skeleton-bar-title" />
      </header>
      <div className="section-card-body">
        <div className="skeleton-bar" style={{ width: "92%" }} />
        <div className="skeleton-bar" style={{ width: "78%" }} />
        <div className="skeleton-bar" style={{ width: "85%" }} />
        <div className="skeleton-bar" style={{ width: "60%" }} />
      </div>
    </section>
  );
}

function AngleCard({ angle, onPick, onSave, isSaved, testid }) {
  const cat = ANGLE_CAT[angle.category] || ANGLE_CAT.curiosity;
  return (
    <div className="angle-card" data-testid={testid} style={{ "--cat-color": cat.color }}>
      <button
        type="button"
        className="angle-save-btn"
        data-testid={`${testid}-save`}
        onClick={(e) => { e.stopPropagation(); onSave(angle); }}
        aria-label={isSaved ? "Remove from saved angles" : "Save angle for later"}
        title={isSaved ? "Saved" : "Save for later"}
      >
        {isSaved ? <BookmarkCheck size={16} /> : <Bookmark size={16} />}
      </button>
      <button
        type="button"
        className="angle-card-body"
        data-testid={`${testid}-pick`}
        onClick={() => onPick(angle)}
      >
        <span className="angle-category">{cat.label}</span>
        <span className="angle-name">{angle.name}</span>
        <span className="angle-framing">{angle.framing}</span>
        <span className="angle-pick-hint"><ChevronRight size={12} /> Use this angle</span>
      </button>
    </div>
  );
}

// =====================================================================
// Phone-frame Shorts result body
// =====================================================================
function ShortPhoneBody({ shortBody }) {
  if (!shortBody) return null;
  // Parse the [HOOK — 0:00–0:03], [BODY — ...], [CTA — ...] blocks, stripping
  // inline directive cues and markdown bold so the phone reads cleanly.
  const blocks = [];
  const re = /^\s*\[(HOOK|BODY|CTA)([^\]]*)\]\s*$/gim;
  const lines = shortBody.split(/\r?\n/);
  let current = null;
  for (const ln of lines) {
    const m = ln.match(/^\s*\[(HOOK|BODY|CTA)([^\]]*)\]\s*$/i);
    if (m) {
      if (current) blocks.push(current);
      current = { label: m[1].toUpperCase(), time: (m[2] || "").replace(/^\s*[—–-]\s*/, "").trim(), lines: [] };
    } else if (current) {
      const trimmed = ln.trim();
      if (trimmed) current.lines.push(trimmed);
    }
  }
  if (current) blocks.push(current);
  re.lastIndex = 0;

  const cleanLine = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1");

  return (
    <div className="phone-body" data-testid="phone-body">
      {blocks.map((b, i) => (
        <div key={i} className={`phone-beat phone-beat-${b.label.toLowerCase()}`} data-testid={`phone-beat-${b.label.toLowerCase()}`}>
          <div className="phone-beat-head">
            <span className="phone-beat-label">{b.label}</span>
            {b.time && <span className="phone-beat-time">{b.time}</span>}
          </div>
          <div className="phone-beat-lines">
            {b.lines.map((ln, j) => {
              const isOn = /^\[\s*ON-?SCREEN\s*:/i.test(ln);
              const isBR = /^\[\s*B-?ROLL\s*:/i.test(ln);
              const text = ln.replace(/^\[\s*(ON-?SCREEN|B-?ROLL)\s*:\s*([\s\S]*)\]\s*$/i, "$2");
              if (isOn) return (
                <div key={j} className="phone-cue phone-cue-onscreen" data-testid="phone-cue-onscreen">
                  <span className="phone-cue-tag">TEXT</span> {cleanLine(text)}
                </div>
              );
              if (isBR) return (
                <div key={j} className="phone-cue phone-cue-broll" data-testid="phone-cue-broll">
                  <span className="phone-cue-tag">B-ROLL</span> {cleanLine(text)}
                </div>
              );
              return <p key={j} className="phone-narration">{cleanLine(ln)}</p>;
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// =====================================================================
// MAIN
// =====================================================================
export default function Scripts() {
  const { user } = useAuth();
  const nav = useNavigate();

  // Rotating tagline picked once on mount
  const [tagline] = useState(() => TAGLINES[Math.floor(Math.random() * TAGLINES.length)]);

  // Inputs
  const [mode, setMode] = useState(MODES.LONG);
  const [topic, setTopic] = useState("");
  const [length, setLength] = useState("medium");
  const [platform, setPlatform] = useState("youtube");

  // Apply platform accent token at document root whenever platform OR mode change
  useEffect(() => {
    const root = document.documentElement;
    if (mode === MODES.SHORTS) {
      const p = PLATFORMS.find((x) => x.id === platform);
      if (p) root.style.setProperty("--platform-accent", p.accent);
    } else {
      root.style.removeProperty("--platform-accent");
    }
  }, [mode, platform]);

  // Two-step flow state
  const [step, setStep] = useState(STEPS.TOPIC);
  const [angles, setAngles] = useState([]);            // [{name, framing, category}]
  const [pickedAngle, setPickedAngle] = useState(null);
  const [busy, setBusy] = useState(false);             // angle-fetch or repurpose
  const [generating, setGenerating] = useState(false); // step-2 generation
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState("");
  const [output, setOutput] = useState(null);
  const [history, setHistory] = useState([]);
  const [savedAngles, setSavedAngles] = useState([]);
  const [showSaved, setShowSaved] = useState(false);
  const [toast, setToast] = useState("");

  const pollRef = useRef(null);
  const elapsedRef = useRef(null);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
  }, []);

  const sections = useMemo(() => (output?.text ? parseSections(output.text) : {}), [output]);
  const orderedKeys = output?.mode === "shorts" ? SHORTS_SECTION_ORDER : LONG_SECTION_ORDER;

  const canLong = user?.entitlements?.includes("base");
  const canShorts = user?.entitlements?.includes("shorts");

  useEffect(() => { loadHistory(); loadSavedAngles(); }, []);
  const loadHistory = async () => {
    try { const r = await apiClient.get("/scripts/history"); setHistory(r.data.items || []); } catch {}
  };
  const loadSavedAngles = async () => {
    try { const r = await apiClient.get("/scripts/saved-angles"); setSavedAngles(r.data.items || []); } catch {}
  };

  // ---- Step 1: fetch angles ----
  const fetchAngles = async () => {
    setErr("");
    if (!topic.trim()) { setErr("Add a topic first."); return; }
    if (mode === MODES.LONG && !canLong) { setErr("Long-form requires the base entitlement."); return; }
    if (mode === MODES.SHORTS && !canShorts) { setErr("Shorts requires the shorts entitlement."); return; }
    setBusy(true);
    setAngles([]);
    setPickedAngle(null);
    setOutput(null);
    try {
      const r = await apiClient.post("/scripts/angles", { topic });
      setAngles(r.data.angles || []);
      setStep(STEPS.ANGLES);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not get angles. Try again.");
    } finally {
      setBusy(false);
    }
  };

  // ---- Save / un-save an angle ----
  const angleKey = (a) => `${(a.name || "").toLowerCase()}::${(a.framing || "").toLowerCase()}`;
  const savedKeys = useMemo(() => new Set(savedAngles.map((s) => angleKey(s.angle))), [savedAngles]);

  const toggleSaveAngle = async (a) => {
    const key = angleKey(a);
    const existing = savedAngles.find((s) => angleKey(s.angle) === key);
    if (existing) {
      // Remove
      try {
        await apiClient.delete(`/scripts/saved-angles/${existing.id}`);
        setSavedAngles((arr) => arr.filter((s) => s.id !== existing.id));
        setToast("Removed from saved angles");
      } catch {}
    } else {
      try {
        const r = await apiClient.post("/scripts/saved-angles", { topic, angle: a });
        setSavedAngles((arr) => [r.data, ...arr]);
        setToast("Saved for later");
      } catch {}
    }
  };

  const deleteSavedAngle = async (id) => {
    try {
      await apiClient.delete(`/scripts/saved-angles/${id}`);
      setSavedAngles((arr) => arr.filter((s) => s.id !== id));
    } catch {}
  };

  // ---- Step 2: pick an angle → kick off full generation ----
  const pollJob = (id, onDone) => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
    const startedAt = Date.now();
    setElapsed(0);
    elapsedRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiClient.get(`/scripts/job/${id}`);
        if (r.data.status === "complete" || r.data.status === "failed") {
          clearInterval(pollRef.current); pollRef.current = null;
          clearInterval(elapsedRef.current); elapsedRef.current = null;
          onDone(r.data);
        }
      } catch (e) {
        clearInterval(pollRef.current); pollRef.current = null;
        clearInterval(elapsedRef.current); elapsedRef.current = null;
        onDone({ status: "failed", error: e?.response?.data?.detail || "Network error" });
      }
    }, 2500);
  };

  const pickAngle = async (angleObj, topicOverride) => {
    setErr("");
    setPickedAngle(angleObj);
    setStep(STEPS.GENERATING);
    setGenerating(true);
    setOutput(null);
    const effectiveTopic = (topicOverride || topic).trim();
    try {
      const url = mode === MODES.LONG ? "/scripts/long" : "/scripts/shorts";
      const body = mode === MODES.LONG
        ? { topic: effectiveTopic, length, chosen_angle: angleObj }
        : { topic: effectiveTopic, platform, chosen_angle: angleObj };
      const r = await apiClient.post(url, body);
      pollJob(r.data.id, (final) => {
        setGenerating(false);
        if (final.status === "complete") {
          setOutput(final);
          setStep(STEPS.RESULT);
          loadHistory();
          setTimeout(() => {
            document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 100);
        } else {
          setErr(final.error || "Generation failed. Try again.");
          setStep(STEPS.ANGLES);
        }
      });
    } catch (e) {
      setGenerating(false);
      setErr(e?.response?.data?.detail || "Could not start generation.");
      setStep(STEPS.ANGLES);
    }
  };

  // From "Saved Angles" — load topic + start generation immediately
  const applySavedAngle = (saved) => {
    setTopic(saved.topic || "");
    setMode(MODES.LONG); // user can flip after if they want
    setShowSaved(false);
    pickAngle(saved.angle, saved.topic);
  };

  // ---- Cut into a Short ----
  const repurposeAsShort = async () => {
    if (!output?.text || output.mode !== "long") return;
    if (!canShorts) { setErr("Repurposing requires the shorts entitlement."); return; }
    setBusy(true); setErr("");
    try {
      const r = await apiClient.post("/scripts/repurpose", {
        source_script: output.text, platform,
        angle: pickedAngle?.name || null,
      });
      pollJob(r.data.id, (final) => {
        setBusy(false);
        if (final.status === "complete") {
          setOutput(final);
          loadHistory();
          setTimeout(() => document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
        } else {
          setErr(final.error || "Could not repurpose.");
        }
      });
    } catch (e) {
      setBusy(false);
      setErr(e?.response?.data?.detail || "Could not repurpose.");
    }
  };

  // ---- Copy all sections (markdown) ----
  const copyAll = async () => {
    if (!output?.text) return;
    try {
      await navigator.clipboard.writeText(output.text);
      setToast("Copied entire script.");
    } catch {
      setToast("Copy failed — try again.");
    }
  };

  const useInStudio = () => {
    if (!output?.text) return;
    const narration = extractNarration(output.text);
    const brollPrompts = extractBrollPrompts(output.text);
    const handoff = {
      script: narration, brollPrompts,
      sourceMode: output.mode, topic: output.topic, ts: Date.now(),
    };
    try { localStorage.setItem("f48_handoff_script", JSON.stringify(handoff)); } catch {}
    nav("/studio");
  };

  const loadFromHistory = async (id) => {
    try {
      const r = await apiClient.get(`/scripts/job/${id}`);
      setOutput(r.data);
      setStep(STEPS.RESULT);
      setTimeout(() => document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    } catch {}
  };

  const deleteFromHistory = async (id) => {
    try {
      await apiClient.delete(`/scripts/${id}`);
      setHistory((h) => h.filter((s) => s.id !== id));
      if (output?.id === id) { setOutput(null); setStep(STEPS.TOPIC); }
    } catch {}
  };

  const startOver = () => {
    setStep(STEPS.TOPIC);
    setAngles([]);
    setPickedAngle(null);
    setOutput(null);
    setErr("");
  };

  // ---- Render ----
  const shortsMode = mode === MODES.SHORTS;
  const platformId = shortsMode ? platform : null;

  return (
    <main className={`studio-main scripts-main ${shortsMode ? "is-shorts" : "is-long"}`} data-mode={mode} data-platform={platformId} data-testid="scripts-page">
      <Toast message={toast} onDismiss={() => setToast("")} />

      {/* Hero */}
      <div className="studio-hero">
        <p className="studio-eyebrow" data-testid="scripts-eyebrow">Faceless to Finished · Script Engine</p>
        <h1 className="studio-title" data-testid="scripts-tagline">{tagline}</h1>
        <p className="studio-sub">
          Paste a topic, pick the length or platform, and the engine returns a full faceless script package — hook variations, narration, inline B-roll, captions, hashtags, and production notes.
        </p>
      </div>

      {/* Saved-angles drawer toggle */}
      {savedAngles.length > 0 && (
        <button
          type="button"
          className="saved-angles-toggle"
          data-testid="saved-angles-toggle"
          onClick={() => setShowSaved((v) => !v)}
        >
          <Bookmark size={14} />
          {showSaved ? "Hide" : "Show"} saved angles ({savedAngles.length})
        </button>
      )}

      {showSaved && (
        <div className="saved-angles-panel" data-testid="saved-angles-panel">
          <div className="saved-angles-head">Saved angles</div>
          <div className="saved-angles-grid">
            {savedAngles.map((s) => {
              const cat = ANGLE_CAT[s.angle.category] || ANGLE_CAT.curiosity;
              return (
                <div key={s.id} className="saved-angle-card" data-testid={`saved-angle-${s.id}`} style={{ "--cat-color": cat.color }}>
                  <button
                    type="button"
                    className="saved-angle-body"
                    data-testid={`saved-angle-${s.id}-use`}
                    onClick={() => applySavedAngle(s)}
                  >
                    <span className="angle-category">{cat.label}</span>
                    <span className="angle-name">{s.angle.name}</span>
                    <span className="angle-framing">{s.angle.framing}</span>
                    <span className="saved-angle-topic">Topic: {s.topic}</span>
                  </button>
                  <button
                    type="button"
                    className="icon-btn is-danger"
                    data-testid={`saved-angle-${s.id}-delete`}
                    onClick={() => deleteSavedAngle(s.id)}
                    aria-label="Delete saved angle"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Mode toggle (always visible) */}
      <div className="mode-toggle" role="tablist" data-testid="scripts-mode-toggle">
        <button
          role="tab"
          data-mode="long"
          className={`mode-opt ${mode === MODES.LONG ? "is-active" : ""}`}
          data-testid="scripts-mode-long"
          onClick={() => { setMode(MODES.LONG); startOver(); }}
        >
          <FileText size={14} /> Long-form
        </button>
        <button
          role="tab"
          data-mode="shorts"
          className={`mode-opt ${mode === MODES.SHORTS ? "is-active" : ""}`}
          data-testid="scripts-mode-shorts"
          onClick={() => { setMode(MODES.SHORTS); startOver(); }}
        >
          <Smartphone size={14} /> Shorts
        </button>
      </div>

      {/* Step 1: topic + length/platform */}
      {(step === STEPS.TOPIC || step === STEPS.ANGLES) && (
        <>
          <div className="script-block">
            <span className="script-label">Topic</span>
            <textarea
              className="script-area"
              data-testid="scripts-topic"
              placeholder={mode === MODES.LONG
                ? "e.g. The hidden psychology behind viral faceless YouTube channels…"
                : "e.g. One income idea anyone can start this weekend for free."}
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              rows={3}
              style={{ minHeight: 90 }}
            />
          </div>

          {mode === MODES.LONG ? (
            <div className="settings-grid" data-testid="scripts-settings-long">
              <span className="script-label">Length</span>
              <div className="length-grid">
                {LENGTHS.map((l) => (
                  <button
                    key={l.id}
                    className={`length-card ${length === l.id ? "is-selected" : ""}`}
                    data-testid={`scripts-length-${l.id}`}
                    onClick={() => setLength(l.id)}
                  >
                    <span className="length-name">{l.label}</span>
                    <span className="length-desc">{l.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="settings-grid" data-testid="scripts-settings-shorts">
              <span className="script-label">Platform</span>
              <div className="length-grid platform-grid">
                {PLATFORMS.map((p) => (
                  <button
                    key={p.id}
                    className={`length-card platform-card ${platform === p.id ? "is-selected" : ""}`}
                    data-testid={`scripts-platform-${p.id}`}
                    data-platform={p.id}
                    style={{ "--platform-accent": p.accent }}
                    onClick={() => setPlatform(p.id)}
                  >
                    <span className="length-name">{p.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* CTA — Step 1 → fetch angles */}
          {step === STEPS.TOPIC && (
            <div className="cta-block">
              <button
                className={`cta-btn ${shortsMode ? "is-platform" : ""}`}
                data-testid="scripts-get-angles-btn"
                disabled={busy || !topic.trim() || (mode === MODES.LONG && !canLong) || (mode === MODES.SHORTS && !canShorts)}
                onClick={fetchAngles}
              >
                {busy ? "Brainstorming angles…" : "Show me 4 angles →"}
              </button>
              {err && <p className="cta-error" data-testid="scripts-error">{err}</p>}
            </div>
          )}
        </>
      )}

      {/* Step 2: angle picker */}
      {step === STEPS.ANGLES && angles.length > 0 && (
        <div className="angles-section" data-testid="angles-section">
          <div className="angles-head">
            <div>
              <p className="script-label">Step 2 — Pick your angle</p>
              <p style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 0" }}>
                Each angle is a different way into the topic. Pick the one that fits — we&rsquo;ll build the full script around it.
              </p>
            </div>
            <button className="header-btn" data-testid="angles-back" onClick={startOver}>
              <ArrowLeft size={13} /> Change topic
            </button>
          </div>
          <div className="angles-grid" data-testid="angles-grid">
            {angles.map((a, i) => (
              <AngleCard
                key={i}
                angle={a}
                testid={`angle-card-${i}`}
                isSaved={savedKeys.has(angleKey(a))}
                onPick={pickAngle}
                onSave={toggleSaveAngle}
              />
            ))}
          </div>
        </div>
      )}

      {/* Step 3: skeleton + elapsed counter while Claude generates */}
      {step === STEPS.GENERATING && (
        <div id="scripts-output" className="scripts-output" data-testid="scripts-generating">
          <div className="scripts-output-head">
            <div>
              <p className="script-label" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                <Loader2 size={14} className="spin" /> Generating · {elapsed}s
              </p>
              <h2 className="scripts-output-title">{pickedAngle?.name || topic}</h2>
              {pickedAngle?.framing && (
                <p style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 0", maxWidth: 600 }}>
                  {pickedAngle.framing}
                </p>
              )}
            </div>
          </div>
          <div className="skeleton-stack">
            {(mode === MODES.LONG ? LONG_SECTION_ORDER : SHORTS_SECTION_ORDER)
              .filter((k) => k !== "angles")  // we never generate angles in step 2
              .map((k) => (
                <SkeletonCard key={k} keyName={k} />
              ))}
          </div>
        </div>
      )}

      {/* Result */}
      {step === STEPS.RESULT && output?.text && (
        <div id="scripts-output" className="scripts-output" data-testid="scripts-output">
          <div className="scripts-output-head">
            <div>
              <span className="script-label">Result</span>
              <h2 className="scripts-output-title">{output.topic}</h2>
              {output.chosen_angle?.name && (
                <p style={{ color: "var(--muted)", fontSize: 13, margin: "4px 0 0" }}>
                  Angle: <strong style={{ color: "var(--text)" }}>{output.chosen_angle.name}</strong>
                </p>
              )}
            </div>
            <div className="scripts-output-actions">
              <button className="header-btn" data-testid="scripts-copy-all-btn" onClick={copyAll}>
                <ClipboardCopy size={13} /> Copy all
              </button>
              {output.mode === "long" && (
                <button
                  className="header-btn"
                  data-testid="scripts-repurpose-btn"
                  disabled={!canShorts || busy}
                  onClick={repurposeAsShort}
                  title={!canShorts ? "Requires shorts entitlement" : ""}
                >
                  <Repeat size={13} /> {busy ? "Cutting into a Short…" : "Cut into a Short"}
                </button>
              )}
              <button className="header-btn" data-testid="scripts-use-in-studio" onClick={useInStudio}>
                <Sparkles size={13} /> Send to Studio
              </button>
            </div>
          </div>

          {/* Shorts result: phone-frame layout */}
          {output.mode === "shorts" ? (
            <div className="shorts-layout" data-testid="shorts-layout">
              {/* PLAN column */}
              <div className="shorts-col">
                <h4 className="shorts-col-head">Plan</h4>
                {sections.hooks && <SectionCard keyName="hooks" section={sections.hooks} testid="section-hooks" />}
                {sections.titleVariants && <SectionCard keyName="titleVariants" section={sections.titleVariants} testid="section-titleVariants" />}
                {sections.coverPrompts && <SectionCard keyName="coverPrompts" section={sections.coverPrompts} testid="section-coverPrompts" />}
              </div>
              {/* SCRIPT column — phone */}
              <div className="shorts-col shorts-col-center">
                <h4 className="shorts-col-head">Script</h4>
                <PhoneFrame platform={output.platform || platform}>
                  <ShortPhoneBody shortBody={sections.shortScript?.body || ""} />
                </PhoneFrame>
              </div>
              {/* DISTRIBUTE column */}
              <div className="shorts-col">
                <h4 className="shorts-col-head">Distribute</h4>
                {sections.caption && <SectionCard keyName="caption" section={sections.caption} testid="section-caption" />}
                {sections.hashtags && <SectionCard keyName="hashtags" section={sections.hashtags} testid="section-hashtags" />}
                {sections.onScreen && <SectionCard keyName="onScreen" section={sections.onScreen} testid="section-onScreen" />}
                {sections.broll && <SectionCard keyName="broll" section={sections.broll} testid="section-broll" />}
                {sections.notes && <SectionCard keyName="notes" section={sections.notes} testid="section-notes" />}
              </div>
            </div>
          ) : (
            // Long-form: classic vertical stack of cards
            orderedKeys.map((k) =>
              sections[k] && k !== "angles" ? (
                <SectionCard key={k} keyName={k} section={sections[k]} testid={`section-${k}`} />
              ) : null
            )
          )}
        </div>
      )}

      {/* History */}
      <div className="history-block" data-testid="scripts-history">
        <div className="history-head">Recent scripts</div>
        {history.length === 0 ? (
          <div className="history-empty">No scripts yet. Generate one above.</div>
        ) : (
          <div className="history-list">
            {history.filter((s) => s.status !== "running").map((s) => (
              <div className="history-row" key={s.id} data-testid={`scripts-history-row-${s.id}`}>
                <div className="history-meta" style={{ minWidth: 0, flex: 1 }}>
                  <span className={`history-chip is-${s.mode === "long" ? "avatar" : "faceless"}`}>
                    {s.mode === "long" ? "Long" : "Short"}
                  </span>
                  <span style={{ color: "var(--text)", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {s.topic}
                  </span>
                  <span className="history-date">{fmtDate(s.created_at)}</span>
                </div>
                <div className="history-actions">
                  <button className="icon-btn" onClick={() => loadFromHistory(s.id)} data-testid={`scripts-history-open-${s.id}`} aria-label="Open">
                    <FileText size={14} />
                  </button>
                  <button className="icon-btn is-danger" onClick={() => deleteFromHistory(s.id)} data-testid={`scripts-history-delete-${s.id}`} aria-label="Delete">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
