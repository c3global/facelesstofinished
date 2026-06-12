import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Sparkles,
  FileText,
  Smartphone,
  Repeat,
  Bookmark,
  ArrowLeft,
  ClipboardCopy,
  Layers,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { apiClient, useAuth } from "../App";
import {
  parseSections,
  LONG_SECTION_ORDER,
  SHORTS_SECTION_ORDER,
  extractNarration,
  extractBrollPrompts,
  parseSprintVariants,
} from "../utils/parser";
import PhoneFrame from "../components/PhoneFrame";
import Toast from "../components/Toast";
import { SectionCard, SkeletonCard } from "../components/scripts/SectionCard";
import { AngleCard } from "../components/scripts/AngleCard";
import ShortPhoneBody from "../components/scripts/ShortPhoneBody";
import SavedAnglesPanel from "../components/scripts/SavedAnglesPanel";
import ScriptHistoryList from "../components/scripts/ScriptHistoryList";
import GenProgress from "../components/scripts/GenProgress";
import SprintResult from "../components/scripts/SprintResult";

const MODES = { LONG: "long", SHORTS: "shorts" };
const STEPS = {
  TOPIC: "topic",
  ANGLES: "angles",
  GENERATING: "generating",
  RESULT: "result",
};

const LENGTHS = [
  { id: "short", label: "Short", desc: "5–8 min · 800–1,200 words" },
  { id: "medium", label: "Medium", desc: "10–15 min · 1,500–2,200 words" },
  { id: "long", label: "Long", desc: "18–25 min · 2,700–3,800 words" },
];
const PLATFORMS = [
  { id: "youtube", label: "YouTube Shorts", accent: "#FF0033" },
  { id: "reels", label: "Instagram Reels", accent: "#E1306C" },
  { id: "tiktok", label: "TikTok", accent: "#25F4EE" },
];

const TAGLINES = [
  "Write a script that gets watched.",
  "Type a topic. Get a complete script.",
  "From blank page to ready-to-record — in seconds.",
];

const angleKey = (a) =>
  `${(a?.name || "").toLowerCase()}::${(a?.framing || "").toLowerCase()}`;

export default function Scripts() {
  const { user } = useAuth();
  const nav = useNavigate();

  const [tagline] = useState(
    () => TAGLINES[Math.floor(Math.random() * TAGLINES.length)]
  );

  // Inputs
  const [mode, setMode] = useState(MODES.LONG);
  const [topic, setTopic] = useState("");
  const [length, setLength] = useState("medium");
  const [platform, setPlatform] = useState("youtube");
  const [sprint, setSprint] = useState(false);
  const [multiPlatform, setMultiPlatform] = useState(false);

  // Apply platform accent CSS variable
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
  const [angles, setAngles] = useState([]);
  const [pickedAngle, setPickedAngle] = useState(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState("");
  const [output, setOutput] = useState(null);
  // Multi-platform results: array of { platform, id, status, output? }
  const [multiJobs, setMultiJobs] = useState([]);
  const [activeTab, setActiveTab] = useState("youtube");

  const [history, setHistory] = useState([]);
  const [savedAngles, setSavedAngles] = useState([]);
  const [showSaved, setShowSaved] = useState(false);
  const [toast, setToast] = useState("");
  const [promotingIndex, setPromotingIndex] = useState(null);

  const pollRef = useRef(null);
  const elapsedRef = useRef(null);
  const multiPollRef = useRef(null);

  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (elapsedRef.current) clearInterval(elapsedRef.current);
      if (multiPollRef.current) clearInterval(multiPollRef.current);
    },
    []
  );

  const sections = useMemo(
    () => (output?.text ? parseSections(output.text) : {}),
    [output]
  );
  const sprintVariants = useMemo(
    () => (output?.mode === "sprint" && output?.text ? parseSprintVariants(output.text) : []),
    [output]
  );
  const orderedKeys =
    output?.mode === "shorts" ? SHORTS_SECTION_ORDER : LONG_SECTION_ORDER;

  const canLong = user?.entitlements?.includes("base");
  const canShorts = user?.entitlements?.includes("shorts");

  useEffect(() => {
    loadHistory();
    loadSavedAngles();
  }, []);

  const loadHistory = async () => {
    try {
      const r = await apiClient.get("/scripts/history");
      setHistory(r.data.items || []);
    } catch {}
  };
  const loadSavedAngles = async () => {
    try {
      const r = await apiClient.get("/scripts/saved-angles");
      setSavedAngles(r.data.items || []);
    } catch {}
  };

  const savedKeys = useMemo(
    () => new Set(savedAngles.map((s) => angleKey(s.angle))),
    [savedAngles]
  );

  // Sprint AND multi-platform both skip the angle picker step:
  //   - sprint generates its own 5 distinct angles internally
  //   - multi-platform fans out one job per platform; angle picking would
  //     force the user to pick once and use the same angle for all 3, which
  //     defeats the parallel-discovery point of the feature
  const skipAngleStep = mode === MODES.SHORTS && (sprint || multiPlatform);

  // ---- Step 1: fetch angles ----
  const fetchAngles = async () => {
    setErr("");
    if (!topic.trim()) {
      setErr("Add a topic first.");
      return;
    }
    if (mode === MODES.LONG && !canLong) {
      setErr("Long-form requires the base entitlement.");
      return;
    }
    if (mode === MODES.SHORTS && !canShorts) {
      setErr("Shorts requires the shorts entitlement.");
      return;
    }

    // Sprint / multi-platform: skip the angle picker entirely.
    if (skipAngleStep) {
      kickoffGeneration(null, topic);
      return;
    }

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

  const toggleSaveAngle = async (a) => {
    const key = angleKey(a);
    const existing = savedAngles.find((s) => angleKey(s.angle) === key);
    if (existing) {
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

  // ---- Generic job polling ----
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
          clearInterval(pollRef.current);
          pollRef.current = null;
          clearInterval(elapsedRef.current);
          elapsedRef.current = null;
          onDone(r.data);
        }
      } catch (e) {
        clearInterval(pollRef.current);
        pollRef.current = null;
        clearInterval(elapsedRef.current);
        elapsedRef.current = null;
        onDone({
          status: "failed",
          error: e?.response?.data?.detail || "Network error",
        });
      }
    }, 2500);
  };

  // ---- Multi-platform polling: tracks N jobs at once ----
  const pollMultiJobs = (initialJobs) => {
    if (multiPollRef.current) clearInterval(multiPollRef.current);
    if (elapsedRef.current) clearInterval(elapsedRef.current);
    const startedAt = Date.now();
    setElapsed(0);
    elapsedRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    multiPollRef.current = setInterval(async () => {
      const updates = await Promise.all(
        initialJobs.map(async (j) => {
          if (j.status === "complete" || j.status === "failed") return j;
          try {
            const r = await apiClient.get(`/scripts/job/${j.id}`);
            return { ...j, status: r.data.status, output: r.data };
          } catch {
            return { ...j, status: "failed", error: "Network error" };
          }
        })
      );

      // Mutate the working copy in place so the next tick polls fresh statuses
      initialJobs.splice(0, initialJobs.length, ...updates);
      setMultiJobs([...updates]);

      const allDone = updates.every(
        (j) => j.status === "complete" || j.status === "failed"
      );
      if (allDone) {
        clearInterval(multiPollRef.current);
        multiPollRef.current = null;
        clearInterval(elapsedRef.current);
        elapsedRef.current = null;
        // pick the first complete as the active tab
        const firstComplete = updates.find((j) => j.status === "complete");
        if (firstComplete) {
          setActiveTab(firstComplete.platform);
          setOutput(firstComplete.output);
        } else {
          setErr("All platforms failed. Try again.");
        }
        setStep(STEPS.RESULT);
        loadHistory();
      }
    }, 2500);
  };

  // ---- Kickoff generation (called after angle pick OR direct from step 1) ----
  const kickoffGeneration = async (angleObj, topicOverride) => {
    setErr("");
    setPickedAngle(angleObj);
    setStep(STEPS.GENERATING);
    setOutput(null);
    setMultiJobs([]);
    const effectiveTopic = (topicOverride || topic).trim();

    // ---- Multi-platform: fire 3 parallel jobs ----
    if (mode === MODES.SHORTS && multiPlatform) {
      try {
        const responses = await Promise.all(
          PLATFORMS.map((p) =>
            apiClient.post("/scripts/shorts", {
              topic: effectiveTopic,
              platform: p.id,
              chosen_angle: angleObj || undefined,
              sprint: false,
            })
          )
        );
        const jobs = responses.map((r, i) => ({
          platform: PLATFORMS[i].id,
          id: r.data.id,
          status: "running",
          output: null,
        }));
        setMultiJobs(jobs);
        setActiveTab(PLATFORMS[0].id);
        pollMultiJobs(jobs);
      } catch (e) {
        setErr(e?.response?.data?.detail || "Could not start generation.");
        setStep(STEPS.TOPIC);
      }
      return;
    }

    // ---- Sprint or single-shorts or long-form ----
    try {
      const url = mode === MODES.LONG ? "/scripts/long" : "/scripts/shorts";
      const body =
        mode === MODES.LONG
          ? { topic: effectiveTopic, length, chosen_angle: angleObj || undefined }
          : {
              topic: effectiveTopic,
              platform,
              chosen_angle: angleObj || undefined,
              sprint,
            };
      const r = await apiClient.post(url, body);
      pollJob(r.data.id, (final) => {
        if (final.status === "complete") {
          setOutput(final);
          setStep(STEPS.RESULT);
          loadHistory();
          setTimeout(
            () =>
              document.getElementById("scripts-output")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              }),
            100
          );
        } else {
          setErr(final.error || "Generation failed. Try again.");
          setStep(skipAngleStep ? STEPS.TOPIC : STEPS.ANGLES);
        }
      });
    } catch (e) {
      setErr(e?.response?.data?.detail || "Could not start generation.");
      setStep(skipAngleStep ? STEPS.TOPIC : STEPS.ANGLES);
    }
  };

  const applySavedAngle = (saved) => {
    setTopic(saved.topic || "");
    setMode(MODES.LONG);
    setShowSaved(false);
    kickoffGeneration(saved.angle, saved.topic);
  };

  // ---- Promote one Sprint variant to a full single-short generation ----
  // Reuses the existing /scripts/shorts pipeline with sprint:false and a
  // synthesized chosen_angle pulled out of the variant. No new API cost
  // pattern — same per-short token spend as a normal single-Short generation.
  const promoteVariant = async (variant) => {
    if (!output || output.mode !== "sprint") return;
    setErr("");
    setPromotingIndex(variant.index);
    const variantPlatform = output.platform || platform;
    const variantTopic = output.topic;
    const chosenAngle = {
      name: variant.name,
      framing: variant.angle || `Sprint variant ${variant.index}`,
      category: variant.category || "curiosity",
    };
    try {
      const r = await apiClient.post("/scripts/shorts", {
        topic: variantTopic,
        platform: variantPlatform,
        chosen_angle: chosenAngle,
        sprint: false,
      });
      // Switch the page into the GENERATING view so the progress bar shows.
      setPickedAngle(chosenAngle);
      setMode(MODES.SHORTS);
      setPlatform(variantPlatform);
      setSprint(false);
      setMultiPlatform(false);
      setMultiJobs([]);
      setOutput(null);
      setStep(STEPS.GENERATING);
      pollJob(r.data.id, (final) => {
        setPromotingIndex(null);
        if (final.status === "complete") {
          setOutput(final);
          setStep(STEPS.RESULT);
          loadHistory();
          setTimeout(
            () =>
              document.getElementById("scripts-output")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              }),
            100
          );
        } else {
          setErr(final.error || "Promotion failed. Try again.");
          setStep(STEPS.RESULT);
        }
      });
    } catch (e) {
      setPromotingIndex(null);
      setErr(e?.response?.data?.detail || "Could not promote variant.");
    }
  };

  // ---- Cut into a Short ----
  const repurposeAsShort = async () => {
    if (!output?.text || output.mode !== "long") return;
    if (!canShorts) {
      setErr("Repurposing requires the shorts entitlement.");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const r = await apiClient.post("/scripts/repurpose", {
        source_script: output.text,
        platform,
        angle: pickedAngle?.name || null,
      });
      pollJob(r.data.id, (final) => {
        setBusy(false);
        if (final.status === "complete") {
          setOutput(final);
          loadHistory();
          setTimeout(
            () =>
              document.getElementById("scripts-output")?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              }),
            100
          );
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
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(output.text);
        copied = true;
      }
    } catch {
      /* fall through */
    }
    if (!copied) {
      try {
        const ta = document.createElement("textarea");
        ta.value = output.text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        copied = document.execCommand("copy");
        document.body.removeChild(ta);
      } catch {}
    }
    setToast(
      copied
        ? "Copied entire script."
        : "Copy failed — try selecting & copying manually."
    );
  };

  const useInStudio = () => {
    if (!output?.text) return;
    const narration = extractNarration(output.text);
    const brollPrompts = extractBrollPrompts(output.text);
    const handoff = {
      script: narration,
      brollPrompts,
      sourceMode: output.mode,
      topic: output.topic,
      ts: Date.now(),
    };
    try {
      localStorage.setItem("f48_handoff_script", JSON.stringify(handoff));
    } catch {}
    nav("/studio");
  };

  const loadFromHistory = async (id) => {
    try {
      const r = await apiClient.get(`/scripts/job/${id}`);
      setOutput(r.data);
      setMultiJobs([]);
      setStep(STEPS.RESULT);
      setTimeout(
        () =>
          document.getElementById("scripts-output")?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          }),
        100
      );
    } catch {}
  };

  const deleteFromHistory = async (id) => {
    try {
      await apiClient.delete(`/scripts/${id}`);
      setHistory((h) => h.filter((s) => s.id !== id));
      if (output?.id === id) {
        setOutput(null);
        setStep(STEPS.TOPIC);
      }
    } catch {}
  };

  const startOver = () => {
    setStep(STEPS.TOPIC);
    setAngles([]);
    setPickedAngle(null);
    setOutput(null);
    setMultiJobs([]);
    setErr("");
  };

  // When switching to/from Shorts or toggling sprint/multi-platform, reset
  // the conflicting flags so the UI stays coherent (can't be both sprint and
  // multi-platform — the combinatorial output would explode).
  const onModeChange = (next) => {
    setMode(next);
    if (next === MODES.LONG) {
      setSprint(false);
      setMultiPlatform(false);
    }
    startOver();
  };

  // Selecting one flag clears the other so they remain mutually exclusive.
  // Clicking the Sprint pill always turns it ON (not a toggle) — the Single
  // pill handles the off-case, so this avoids surprising double-click flicker.
  const enableSprint = () => {
    setSprint(true);
    setMultiPlatform(false);
  };
  const toggleMultiPlatform = (checked) => {
    setMultiPlatform(checked);
    if (checked) setSprint(false);
  };

  // ---- Tab switching for multi-platform ----
  const switchTab = (platformId) => {
    const job = multiJobs.find((j) => j.platform === platformId);
    setActiveTab(platformId);
    if (job?.status === "complete" && job.output) setOutput(job.output);
    // Apply the platform's accent token so phone color updates
    const p = PLATFORMS.find((x) => x.id === platformId);
    if (p) document.documentElement.style.setProperty("--platform-accent", p.accent);
  };

  const shortsMode = mode === MODES.SHORTS;
  const platformId = shortsMode ? platform : null;

  // CTA copy varies with the active sub-mode
  let ctaCopy;
  if (busy) ctaCopy = "Brainstorming angles…";
  else if (sprint) ctaCopy = "Generate 5-short content sprint →";
  else if (multiPlatform) ctaCopy = "Generate for all 3 platforms →";
  else ctaCopy = "Show me 4 angles →";

  return (
    <main
      className={`studio-main scripts-main ${shortsMode ? "is-shorts" : "is-long"}`}
      data-mode={mode}
      data-platform={platformId}
      data-testid="scripts-page"
    >
      <Toast message={toast} onDismiss={() => setToast("")} />

      {/* Hero */}
      <div className="studio-hero">
        <p className="studio-eyebrow" data-testid="scripts-eyebrow">
          Faceless to Finished · Script Engine
        </p>
        <h1 className="studio-title" data-testid="scripts-tagline">
          {tagline}
        </h1>
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
        <SavedAnglesPanel
          savedAngles={savedAngles}
          onApply={applySavedAngle}
          onDelete={deleteSavedAngle}
        />
      )}

      {/* Mode toggle */}
      <div className="mode-toggle" role="tablist" data-testid="scripts-mode-toggle">
        <button
          role="tab"
          data-mode="long"
          className={`mode-opt ${mode === MODES.LONG ? "is-active" : ""}`}
          data-testid="scripts-mode-long"
          onClick={() => onModeChange(MODES.LONG)}
        >
          <FileText size={14} /> Long-form
        </button>
        <button
          role="tab"
          data-mode="shorts"
          className={`mode-opt ${mode === MODES.SHORTS ? "is-active" : ""}`}
          data-testid="scripts-mode-shorts"
          onClick={() => onModeChange(MODES.SHORTS)}
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
              placeholder={
                mode === MODES.LONG
                  ? "e.g. The hidden psychology behind viral faceless YouTube channels…"
                  : "e.g. One income idea anyone can start this weekend for free."
              }
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
              {/* Sprint pill toggle */}
              <span className="script-label">Sprint mode</span>
              <div className="sprint-toggle" data-testid="sprint-toggle">
                <button
                  className={`sprint-opt ${!sprint ? "is-active" : ""}`}
                  data-testid="sprint-opt-single"
                  onClick={() => setSprint(false)}
                >
                  Single short
                </button>
                <button
                  className={`sprint-opt ${sprint ? "is-active" : ""}`}
                  data-testid="sprint-opt-sprint"
                  onClick={enableSprint}
                >
                  <Layers size={12} /> Content sprint
                  <span className="sprint-opt-count">5</span>
                </button>
              </div>

              {/* Platform cards — hidden when multi-platform is on */}
              {!multiPlatform && (
                <>
                  <span className="script-label" style={{ marginTop: 6 }}>Platform</span>
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
                </>
              )}

              {/* Multi-platform checkbox — disabled when sprint is on */}
              {!sprint && (
                <label
                  className="multi-platform-row"
                  data-testid="multi-platform-row"
                  style={{ marginTop: 8 }}
                >
                  <input
                    type="checkbox"
                    data-testid="multi-platform-checkbox"
                    checked={multiPlatform}
                    onChange={(e) => toggleMultiPlatform(e.target.checked)}
                  />
                  Generate for all 3 platforms at once
                </label>
              )}
            </div>
          )}

          {/* CTA — Step 1 → fetch angles (or skip to gen for sprint/multi) */}
          {step === STEPS.TOPIC && (
            <div className="cta-block">
              <button
                className={`cta-btn ${shortsMode ? "is-platform" : ""}`}
                data-testid="scripts-get-angles-btn"
                disabled={
                  busy ||
                  !topic.trim() ||
                  (mode === MODES.LONG && !canLong) ||
                  (mode === MODES.SHORTS && !canShorts)
                }
                onClick={fetchAngles}
              >
                {ctaCopy}
              </button>
              {err && (
                <p className="cta-error" data-testid="scripts-error">
                  {err}
                </p>
              )}
            </div>
          )}
        </>
      )}

      {/* Step 2: angle picker (skipped in sprint / multi-platform mode) */}
      {step === STEPS.ANGLES && angles.length > 0 && (
        <div className="angles-section" data-testid="angles-section">
          <div className="angles-head">
            <div>
              <p className="script-label">Step 2 — Pick your angle</p>
              <p
                style={{
                  color: "var(--muted)",
                  fontSize: 13,
                  margin: "4px 0 0",
                }}
              >
                Each angle is a different way into the topic. Pick the one that fits — we&rsquo;ll build the full script around it.
              </p>
            </div>
            <button
              className="header-btn"
              data-testid="angles-back"
              onClick={startOver}
            >
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
                onPick={(angleObj) => kickoffGeneration(angleObj)}
                onSave={toggleSaveAngle}
              />
            ))}
          </div>
        </div>
      )}

      {/* Step 3: progress bar + skeleton stack while Claude generates */}
      {step === STEPS.GENERATING && (
        <div
          id="scripts-output"
          className="scripts-output"
          data-testid="scripts-generating"
        >
          <div className="scripts-output-head">
            <div>
              <h2 className="scripts-output-title">
                {pickedAngle?.name || (sprint ? "Content sprint" : topic)}
              </h2>
              {pickedAngle?.framing && (
                <p
                  style={{
                    color: "var(--muted)",
                    fontSize: 13,
                    margin: "4px 0 0",
                    maxWidth: 600,
                  }}
                >
                  {pickedAngle.framing}
                </p>
              )}
            </div>
          </div>

          <GenProgress
            mode={sprint ? "sprint" : mode === MODES.LONG ? "long" : "shorts"}
            elapsed={elapsed}
          />

          {/* Multi-platform: show per-platform status row */}
          {multiPlatform && multiJobs.length > 0 ? (
            <div className="platform-tabs" data-testid="multi-platform-status">
              {multiJobs.map((j) => {
                const p = PLATFORMS.find((x) => x.id === j.platform);
                return (
                  <span
                    key={j.platform}
                    className="platform-tab"
                    data-testid={`multi-status-${j.platform}`}
                    style={{ "--tab-accent": p?.accent }}
                  >
                    <span className={`platform-tab-status is-${j.status}`} />
                    {p?.label || j.platform}
                  </span>
                );
              })}
            </div>
          ) : (
            <div className="skeleton-stack">
              {(sprint
                ? ["shortScript", "shortScript", "shortScript", "shortScript", "shortScript"]
                : mode === MODES.LONG
                ? LONG_SECTION_ORDER
                : SHORTS_SECTION_ORDER)
                .filter((k) => k !== "angles")
                .map((k, i) => (
                  <SkeletonCard key={`${k}-${i}`} keyName={k} />
                ))}
            </div>
          )}
        </div>
      )}

      {/* Result */}
      {step === STEPS.RESULT && output?.text && (
        <div
          id="scripts-output"
          className="scripts-output"
          data-testid="scripts-output"
        >
          <div className="scripts-output-head">
            <div>
              <span className="script-label">Result</span>
              <h2 className="scripts-output-title">{output.topic}</h2>
              {output.chosen_angle?.name && (
                <p
                  style={{
                    color: "var(--muted)",
                    fontSize: 13,
                    margin: "4px 0 0",
                  }}
                >
                  Angle:{" "}
                  <strong style={{ color: "var(--text)" }}>
                    {output.chosen_angle.name}
                  </strong>
                </p>
              )}
            </div>
            <div className="scripts-output-actions">
              <button
                className="header-btn"
                data-testid="scripts-copy-all-btn"
                onClick={copyAll}
              >
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
                  <Repeat size={13} />{" "}
                  {busy ? "Cutting into a Short…" : "Cut into a Short"}
                </button>
              )}
              {output.mode !== "sprint" && (
                <button
                  className="header-btn"
                  data-testid="scripts-use-in-studio"
                  onClick={useInStudio}
                >
                  <Sparkles size={13} /> Send to Studio
                </button>
              )}
            </div>
          </div>

          {/* Multi-platform tabs */}
          {multiJobs.length > 0 && (
            <div className="platform-tabs" data-testid="platform-tabs">
              {multiJobs.map((j) => {
                const p = PLATFORMS.find((x) => x.id === j.platform);
                return (
                  <button
                    key={j.platform}
                    type="button"
                    className={`platform-tab ${activeTab === j.platform ? "is-active" : ""}`}
                    data-testid={`platform-tab-${j.platform}`}
                    style={{ "--tab-accent": p?.accent }}
                    onClick={() => switchTab(j.platform)}
                  >
                    <span className={`platform-tab-status is-${j.status}`} />
                    {p?.label || j.platform}
                  </button>
                );
              })}
            </div>
          )}

          {/* Sprint result */}
          {output.mode === "sprint" ? (
            <SprintResult
              variants={sprintVariants}
              platform={output.platform || platform}
              onPromote={promoteVariant}
              promotingIndex={promotingIndex}
            />
          ) : output.mode === "shorts" ? (
            <div className="shorts-layout" data-testid="shorts-layout">
              {/* PLAN column */}
              <div className="shorts-col">
                <h4 className="shorts-col-head">Plan</h4>
                {sections.hooks && (
                  <SectionCard
                    keyName="hooks"
                    section={sections.hooks}
                    testid="section-hooks"
                    revealIndex={0}
                  />
                )}
                {sections.titleVariants && (
                  <SectionCard
                    keyName="titleVariants"
                    section={sections.titleVariants}
                    testid="section-titleVariants"
                    revealIndex={1}
                  />
                )}
                {sections.coverPrompts && (
                  <SectionCard
                    keyName="coverPrompts"
                    section={sections.coverPrompts}
                    testid="section-coverPrompts"
                    revealIndex={2}
                  />
                )}
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
                {sections.caption && (
                  <SectionCard
                    keyName="caption"
                    section={sections.caption}
                    testid="section-caption"
                    revealIndex={3}
                  />
                )}
                {sections.hashtags && (
                  <SectionCard
                    keyName="hashtags"
                    section={sections.hashtags}
                    testid="section-hashtags"
                    revealIndex={4}
                  />
                )}
                {sections.onScreen && (
                  <SectionCard
                    keyName="onScreen"
                    section={sections.onScreen}
                    testid="section-onScreen"
                    revealIndex={5}
                  />
                )}
                {sections.broll && (
                  <SectionCard
                    keyName="broll"
                    section={sections.broll}
                    testid="section-broll"
                    revealIndex={6}
                  />
                )}
                {sections.notes && (
                  <SectionCard
                    keyName="notes"
                    section={sections.notes}
                    testid="section-notes"
                    revealIndex={7}
                  />
                )}
              </div>
            </div>
          ) : (
            // Long-form: classic vertical stack of cards
            orderedKeys.map((k, i) =>
              sections[k] && k !== "angles" ? (
                <SectionCard
                  key={k}
                  keyName={k}
                  section={sections[k]}
                  testid={`section-${k}`}
                  revealIndex={i}
                />
              ) : null
            )
          )}
        </div>
      )}

      <ScriptHistoryList
        history={history}
        onOpen={loadFromHistory}
        onDelete={deleteFromHistory}
      />
    </main>
  );
}
