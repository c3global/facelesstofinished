import React, { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Trash2, Sparkles, FileText, Smartphone, Repeat, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { apiClient, useAuth } from "../App";
import { parseSections, LONG_SECTION_ORDER, SHORTS_SECTION_ORDER } from "../utils/parser";

const MODES = { LONG: "long", SHORTS: "shorts" };
const LENGTHS = [
  { id: "short",  label: "Short", desc: "5–8 min · 800–1,200 words" },
  { id: "medium", label: "Medium", desc: "10–15 min · 1,500–2,200 words" },
  { id: "long",   label: "Long", desc: "18–25 min · 2,700–3,800 words" },
];
const PLATFORMS = [
  { id: "youtube", label: "YouTube Shorts" },
  { id: "reels",   label: "Instagram Reels" },
  { id: "tiktok",  label: "TikTok" },
];

const SECTION_LABEL = {
  angles: "Topic Angles",
  concept: "Video Concept",
  hooks: "Hook Variations",
  outline: "Outline",
  script: "Narration Script",
  transitions: "Transitions",
  broll: "B-Roll Shot List",
  notes: "Production Notes",
  shortScript: "Short-Form Script",
  onScreen: "On-Screen Text",
  caption: "Caption",
  hashtags: "Hashtags",
  titleVariants: "Title / Thumbnail Variants",
  coverPrompts: "Cover Image Prompts",
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
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {}
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
      <pre className="section-card-body">{section.body}</pre>
    </section>
  );
}

export default function Scripts() {
  const { user } = useAuth();
  const nav = useNavigate();

  const [mode, setMode] = useState(MODES.LONG);
  const [topic, setTopic] = useState("");
  const [length, setLength] = useState("medium");
  const [platform, setPlatform] = useState("youtube");
  const [angle, setAngle] = useState("");

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [output, setOutput] = useState(null); // { text, mode, ... }
  const [history, setHistory] = useState([]);
  const [repurposeBusy, setRepurposeBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const pollRef = useRef(null);
  const elapsedRef = useRef(null);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
  }, []);

  const sections = useMemo(() => (output?.text ? parseSections(output.text) : {}), [output]);
  const orderedKeys = output?.mode === "shorts" ? SHORTS_SECTION_ORDER : LONG_SECTION_ORDER;

  // Gate by entitlements: long requires 'base', shorts requires 'shorts'
  const canLong = user?.entitlements?.includes("base");
  const canShorts = user?.entitlements?.includes("shorts");

  useEffect(() => { loadHistory(); }, []);
  const loadHistory = async () => {
    try {
      const r = await apiClient.get("/scripts/history");
      setHistory(r.data.items || []);
    } catch {}
  };

  // Poll a queued/running script job until it completes or fails.
  const pollJob = (scriptId, onDone) => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
    const startedAt = Date.now();
    setElapsed(0);
    elapsedRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    pollRef.current = setInterval(async () => {
      try {
        const r = await apiClient.get(`/scripts/job/${scriptId}`);
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

  const generate = async () => {
    setErr("");
    if (!topic.trim()) { setErr("Add a topic first."); return; }
    if (mode === MODES.LONG && !canLong) { setErr("Long-form requires the base entitlement."); return; }
    if (mode === MODES.SHORTS && !canShorts) { setErr("Shorts requires the shorts entitlement."); return; }

    setBusy(true);
    setOutput(null);
    try {
      const url = mode === MODES.LONG ? "/scripts/long" : "/scripts/shorts";
      const body = mode === MODES.LONG
        ? { topic, length, angle: angle || null }
        : { topic, platform, angle: angle || null };
      const r = await apiClient.post(url, body);
      // Server returns the queued record immediately
      pollJob(r.data.id, (final) => {
        setBusy(false);
        if (final.status === "complete") {
          setOutput(final);
          loadHistory();
          setTimeout(() => {
            document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 100);
        } else {
          setErr(final.error || "Generation failed. Try again.");
        }
      });
    } catch (e) {
      setBusy(false);
      setErr(e?.response?.data?.detail || "Could not start generation. Try again.");
    }
  };

  const repurposeAsShort = async () => {
    if (!output?.text || output.mode !== "long") return;
    if (!canShorts) { setErr("Repurposing requires the shorts entitlement."); return; }
    setRepurposeBusy(true);
    setErr("");
    try {
      const r = await apiClient.post("/scripts/repurpose", {
        source_script: output.text,
        platform,
        angle: angle || null,
      });
      pollJob(r.data.id, (final) => {
        setRepurposeBusy(false);
        if (final.status === "complete") {
          setOutput(final);
          loadHistory();
          setTimeout(() => {
            document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 100);
        } else {
          setErr(final.error || "Could not repurpose. Try again.");
        }
      });
    } catch (e) {
      setRepurposeBusy(false);
      setErr(e?.response?.data?.detail || "Could not repurpose. Try again.");
    }
  };

  const loadFromHistory = async (id) => {
    try {
      const r = await apiClient.get(`/scripts/${id}`);
      setOutput(r.data);
      setTimeout(() => {
        document.getElementById("scripts-output")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch {}
  };

  const deleteFromHistory = async (id) => {
    try {
      await apiClient.delete(`/scripts/${id}`);
      setHistory((h) => h.filter((s) => s.id !== id));
      if (output?.id === id) setOutput(null);
    } catch {}
  };

  const useInStudio = () => {
    if (!output?.text) return;
    try { localStorage.setItem("f48_handoff_script", output.text); } catch {}
    nav("/studio");
  };

  return (
    <main className="studio-main" data-mode={mode} data-testid="scripts-page">
      {/* Hero */}
      <div className="studio-hero">
        <p className="studio-eyebrow" data-testid="scripts-eyebrow">
          Faceless to Finished · Script Engine
        </p>
        <h1 className="studio-title">Write a script that gets watched.</h1>
        <p className="studio-sub">
          Paste a topic, pick the length or platform, and the engine returns a full faceless script package — hook variations, narration, inline B-roll, captions, hashtags, and production notes.
        </p>
      </div>

      {/* Mode toggle */}
      <div className="mode-toggle" role="tablist" data-testid="scripts-mode-toggle">
        <button
          role="tab"
          data-mode="long"
          className={`mode-opt ${mode === MODES.LONG ? "is-active" : ""}`}
          data-testid="scripts-mode-long"
          onClick={() => setMode(MODES.LONG)}
        >
          <FileText size={14} /> Long-form
        </button>
        <button
          role="tab"
          data-mode="shorts"
          className={`mode-opt ${mode === MODES.SHORTS ? "is-active" : ""}`}
          data-testid="scripts-mode-shorts"
          onClick={() => setMode(MODES.SHORTS)}
        >
          <Smartphone size={14} /> Shorts
        </button>
      </div>

      {/* Topic */}
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

      {/* Settings row */}
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
          <div className="length-grid">
            {PLATFORMS.map((p) => (
              <button
                key={p.id}
                className={`length-card ${platform === p.id ? "is-selected" : ""}`}
                data-testid={`scripts-platform-${p.id}`}
                onClick={() => setPlatform(p.id)}
              >
                <span className="length-name">{p.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="script-block">
        <span className="script-label">Angle bias <span style={{ color: "var(--muted)", textTransform: "none", letterSpacing: 0 }}>(optional)</span></span>
        <input
          className="login-input"
          data-testid="scripts-angle"
          placeholder="e.g. underdog story · contrarian take · what nobody tells you"
          value={angle}
          onChange={(e) => setAngle(e.target.value)}
        />
      </div>

      {/* CTA */}
      <div className="cta-block">
        <button
          className="cta-btn"
          data-testid="scripts-generate-btn"
          disabled={busy || !topic.trim() || (mode === MODES.LONG && !canLong) || (mode === MODES.SHORTS && !canShorts)}
          onClick={generate}
        >
          {busy ? `Writing… ${elapsed}s` : "Generate script"}
        </button>
        {!canLong && mode === MODES.LONG && (
          <p className="cta-hint">Long-form requires the base entitlement.</p>
        )}
        {!canShorts && mode === MODES.SHORTS && (
          <p className="cta-hint">Shorts requires the shorts entitlement.</p>
        )}
        {err && <p className="cta-error" data-testid="scripts-error">{err}</p>}
        {busy && (
          <p className="cta-hint" data-testid="scripts-busy">
            <Loader2 size={12} className="spin" /> Claude is thinking. Long-form usually finishes in 60–120s.
          </p>
        )}
      </div>

      {/* Output */}
      {output?.text && (
        <div id="scripts-output" className="scripts-output" data-testid="scripts-output">
          <div className="scripts-output-head">
            <div>
              <span className="script-label">Result</span>
              <h2 className="scripts-output-title">{output.topic}</h2>
            </div>
            <div className="scripts-output-actions">
              {output.mode === "long" && (
                <button
                  className="header-btn"
                  data-testid="scripts-repurpose-btn"
                  disabled={!canShorts || repurposeBusy}
                  onClick={repurposeAsShort}
                  title={!canShorts ? "Requires shorts entitlement" : ""}
                >
                  <Repeat size={13} /> {repurposeBusy ? "Cutting into a Short…" : "Cut into a Short"}
                </button>
              )}
              <button className="header-btn" data-testid="scripts-use-in-studio" onClick={useInStudio}>
                <Sparkles size={13} /> Send to Studio
              </button>
            </div>
          </div>

          {orderedKeys.map((k) =>
            sections[k] ? (
              <SectionCard key={k} keyName={k} section={sections[k]} testid={`section-${k}`} />
            ) : null
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
            {history.map((s) => (
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
                  <button
                    className="icon-btn"
                    onClick={() => loadFromHistory(s.id)}
                    data-testid={`scripts-history-open-${s.id}`}
                    aria-label="Open"
                  >
                    <FileText size={14} />
                  </button>
                  <button
                    className="icon-btn is-danger"
                    onClick={() => deleteFromHistory(s.id)}
                    data-testid={`scripts-history-delete-${s.id}`}
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
    </main>
  );
}
