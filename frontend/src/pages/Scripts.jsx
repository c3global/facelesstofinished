import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { Lock } from "lucide-react";
import { apiClient, useAuth, EntitlementPaywall } from "../App";
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
import { SectionCard, SkeletonCard, markdownToHtml, copyRichText } from "../components/scripts/SectionCard";
import { AngleCard } from "../components/scripts/AngleCard";
import ShortPhoneBody from "../components/scripts/ShortPhoneBody";
import SavedAnglesPanel from "../components/scripts/SavedAnglesPanel";
import ScriptHistoryList from "../components/scripts/ScriptHistoryList";
import GenProgress from "../components/scripts/GenProgress";
import SprintResult, { sprintAllToClipboardText } from "../components/scripts/SprintResult";
import ResultsNavBar from "../components/scripts/ResultsNavBar";

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

// Ordered map of section headers Claude emits → friendly status text.
// Used by the drip-banner to show "Writing hook variations…" etc. while
// streaming. The LATEST header found in the partial text wins.
const LONG_PHASES = [
  ["VIDEO CONCEPT", "Drafting video concept…"],
  ["HOOK VARIATIONS", "Writing hook variations…"],
  ["OUTLINE", "Building outline…"],
  ["FULL NARRATION SCRIPT", "Writing narration…"],
  ["TRANSITIONS", "Composing transitions…"],
  ["B-ROLL SHOT LIST", "Compiling B-roll shot list…"],
  ["PRODUCTION NOTES", "Adding production notes…"],
];
const SHORTS_PHASES = [
  ["HOOK", "Drafting hook…"],
  ["SCRIPT", "Writing the short…"],
  ["CAPTION", "Generating caption…"],
  ["HASHTAGS", "Picking hashtags…"],
  ["B-ROLL", "Listing B-roll…"],
  ["PRODUCTION NOTES", "Adding production notes…"],
];
const SPRINT_PHASES = [
  ["VARIANT 1", "Drafting variant 1 of 5…"],
  ["VARIANT 2", "Drafting variant 2 of 5…"],
  ["VARIANT 3", "Drafting variant 3 of 5…"],
  ["VARIANT 4", "Drafting variant 4 of 5…"],
  ["VARIANT 5", "Drafting variant 5 of 5…"],
];

function currentStreamingPhase(text, mode) {
  if (!text) return "Thinking…";
  const phases =
    mode === "sprint" ? SPRINT_PHASES :
    mode === "shorts" ? SHORTS_PHASES :
    LONG_PHASES;
  let lastMatch = phases[0][1];
  const upper = text.toUpperCase();
  for (const [header, label] of phases) {
    if (upper.includes(header)) lastMatch = label;
  }
  return lastMatch;
}

export default function Scripts() {
  const { user } = useAuth();
  // Per-feature entitlement flags. Backend enforces via _require_entitlement
  // (returns 403), but the frontend mirror lets us show a friendlier paywall
  // card inline instead of an angry error toast when a non-shorts buyer
  // clicks the Shorts mode pill.
  const hasShortsEntitlement = Boolean(user?.entitlements?.includes("shorts"));
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
  // Output toggles (long-form Netlify parity)
  const [includeHooks, setIncludeHooks] = useState(true);
  const [includeBroll, setIncludeBroll] = useState(true);
  const [includeProductionNotes, setIncludeProductionNotes] = useState(true);

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
  // Compare mode: when multi-platform finishes, the user can switch to a
  // side-by-side phone-trio view to A/B all three platforms at once.
  const [compareAll, setCompareAll] = useState(false);

  // Apply platform accent CSS variable. When a Shorts result is loaded from
  // history (or a different platform tab is active), `output?.platform` wins
  // over the user's currently-selected platform pill so the phone rim, status
  // badge, and CTA all switch to that platform's color. Without this, every
  // history-loaded short rendered with whatever rim the user last picked
  // (which is why YouTube history was showing up red regardless of the
  // platform the script was actually written for).
  useEffect(() => {
    const root = document.documentElement;
    if (mode === MODES.SHORTS) {
      const activePlatformId = output?.platform || platform;
      const p = PLATFORMS.find((x) => x.id === activePlatformId);
      if (p) root.style.setProperty("--platform-accent", p.accent);
    } else {
      root.style.removeProperty("--platform-accent");
    }
  }, [mode, platform, output?.platform]);

  const [history, setHistory] = useState([]);
  const [savedAngles, setSavedAngles] = useState([]);
  const [showSaved, setShowSaved] = useState(false);
  const [toast, setToast] = useState("");

  // One-shot welcome banner — read & clear the session-stashed payload set
  // by Login.jsx after a successful sign-in. Fires only when the auth
  // response carried a `welcome` field (Pinball auto-grant on first sign-in).
  // sessionStorage scope means it doesn't replay across tabs / page reloads.
  useEffect(() => {
    let raw;
    try { raw = sessionStorage.getItem("f48_pending_welcome"); } catch { raw = null; }
    if (!raw) return;
    try { sessionStorage.removeItem("f48_pending_welcome"); } catch {}
    try {
      const data = JSON.parse(raw);
      const ents = Array.isArray(data?.entitlements) ? data.entitlements : [];
      if (ents.length === 0) return;
      const label = ents.map((e) => e.charAt(0).toUpperCase() + e.slice(1)).join(" + ");
      setToast(`Welcome to Faceless to Finished — ${label} access unlocked.`);
    } catch {
      /* malformed payload — silent */
    }
  }, []);
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

  // ---- Collapse state for v1.8.0 sticky-nav + per-section toggles ----
  // Set of currently-collapsed section keys (e.g. {"hooks","outline"}).
  // Empty = everything expanded. When `collapseAll()` fires we fill it with
  // every visible key; `expandAll()` clears it. Reset on every new output so
  // newly-generated cards land expanded.
  const [collapsedSections, setCollapsedSections] = useState(() => new Set());
  // Reset collapse state whenever a fresh output lands so newly-generated
  // cards arrive expanded.
  useEffect(() => {
    setCollapsedSections(new Set());
  }, [output?.id]);

  // Which section keys are visible on the current screen — needed for the
  // "Collapse all / Expand all" semantics (we treat a screen as "all
  // collapsed" only when every visible key is in the set).
  const visibleSectionKeys = useMemo(() => {
    if (!output?.text) return [];
    if (output.mode === "shorts") {
      return SHORTS_SECTION_ORDER.filter((k) => sections[k] && k !== "angles");
    }
    if (output.mode === "long") {
      return LONG_SECTION_ORDER.filter((k) => sections[k] && k !== "angles");
    }
    return []; // sprint mode has no section cards, only variant phones
  }, [output, sections]);
  const allCollapsed =
    visibleSectionKeys.length > 0 &&
    visibleSectionKeys.every((k) => collapsedSections.has(k));

  const toggleSection = (key) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const toggleCollapseAll = useCallback(() => {
    // Defensive guard — `every` on an empty array returns vacuous-true and
    // would always set the result to `new Set()`, making this button feel
    // dead. This case showed up on long-form scripts loaded from history
    // where the sections memo briefly settles after `output` flips.
    if (visibleSectionKeys.length === 0) return;
    setCollapsedSections((prev) =>
      visibleSectionKeys.every((k) => prev.has(k))
        ? new Set()
        : new Set(visibleSectionKeys)
    );
  }, [visibleSectionKeys]);

  // ---- Anchor scroll helpers used by the sticky nav bar ----
  // Smooth-scrolls the target section under the sticky bar with a 64px top
  // offset so the heading lands cleanly below it.
  const scrollToAnchor = (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const y = el.getBoundingClientRect().top + window.scrollY - 64;
    window.scrollTo({ top: y, behavior: "smooth" });
  };
  const jumpToScript = () => {
    // Long mode → first section that has a "script" key. Shorts mode →
    // the centre phone-frame column (we tag it with id below).
    if (output?.mode === "long") {
      scrollToAnchor("section-script");
    } else if (output?.mode === "shorts") {
      scrollToAnchor("shorts-script-column");
    } else {
      scrollToAnchor("scripts-output");
    }
  };
  const jumpToShorts = () => scrollToAnchor("sprint-grid");

  // Auto-scroll to the freshly-generated shorts panel (sprint or
  // repurpose) the moment it lands in the DOM. We watch the variant count
  // transitioning from 0 → N. rAF-wrapped so React has actually painted
  // the grid before we measure its position.
  const lastVariantCountRef = useRef(0);
  useEffect(() => {
    const next = sprintVariants.length;
    const prev = lastVariantCountRef.current;
    if (next > 0 && prev === 0) {
      requestAnimationFrame(() => {
        const el = document.getElementById("sprint-grid");
        if (el) {
          const y = el.getBoundingClientRect().top + window.scrollY - 64;
          window.scrollTo({ top: y, behavior: "smooth" });
        }
      });
    }
    lastVariantCountRef.current = next;
  }, [sprintVariants.length]);

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
      // Surface the actual server detail so production-env issues (LLM key
      // missing, balance exhausted, upstream rate limit, etc.) are
      // diagnosable from the UI rather than swallowed into a generic
      // "Try again" — which left Charity stuck on 2026-02-23.
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      let msg = "Could not get angles. Try again.";
      if (detail) {
        msg = String(detail);
      } else if (status === 504 || status === 502 || e?.code === "ECONNABORTED") {
        msg = "The script engine timed out. Try a shorter topic or retry in a moment.";
      } else if (status === 401 || status === 403) {
        msg = "Your session expired. Refresh the page and sign in again.";
      } else if (status >= 500) {
        msg = `Script engine error (HTTP ${status}). Try again in a minute — if it keeps happening, top up your Universal Key balance or contact support.`;
      } else if (!status) {
        msg = "No response from the server. Check your connection or refresh the page.";
      }
      setErr(msg);
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
  // Drip-friendly polling: ticks every 500ms. Whenever the server returns
  // partial text mid-stream, we update `output` so the result view renders
  // whatever sections have completed so far. The job is considered "done"
  // only when status flips to `complete` or `failed`.
  const pollJob = (id, onDone, onPartial) => {
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
        } else if (r.data.text && onPartial) {
          // Live stream — push partial text into the UI.
          onPartial(r.data);
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
    }, 500);
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
          ? {
              topic: effectiveTopic,
              length,
              chosen_angle: angleObj || undefined,
              include_hooks: includeHooks,
              include_broll: includeBroll,
              include_production_notes: includeProductionNotes,
            }
          : {
              topic: effectiveTopic,
              platform,
              chosen_angle: angleObj || undefined,
              sprint,
            };
      const r = await apiClient.post(url, body);
      pollJob(
        r.data.id,
        (final) => {
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
        },
        (partial) => {
          // Drip: as soon as the stream starts producing text, swap to the
          // result view so sections appear as they complete.
          setOutput(partial);
          if (step !== STEPS.RESULT) setStep(STEPS.RESULT);
        },
      );
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

  // ---- Copy all sections (markdown + rich HTML for Google Docs) ----
  // Writes BOTH text/plain and text/html so pasting into Google Docs /
  // Word / Notion preserves headings, B-roll cue colors, and section
  // structure. Falls back to plain-text on browsers without ClipboardItem.
  const copyAll = async () => {
    if (!output?.text) return;
    const html = markdownToHtml(output.text);
    const copied = await copyRichText(output.text, html);
    setToast(
      copied
        ? "Copied — paste into Google Docs to keep headings + colors."
        : "Copy failed — try selecting & copying manually."
    );
    if (copied) {
      // Soft engagement log — fire-and-forget, never block the UI.
      apiClient.post("/activity/log", {
        type: "script_copied",
        detail: { script_id: output.id, mode: output.mode, platform: output.platform },
      }).catch(() => {});
    }
  };

  // ---- Copy all sprint shorts as a single blob (v1.8.0) ----
  // Concatenates each variant's text with markdown headers (`# CURIOSITY`)
  // separated by `---` rules so the user can paste the whole pack into a
  // doc and split it back apart by hand.
  const copyAllShorts = async () => {
    const text = sprintAllToClipboardText(sprintVariants);
    if (!text) return;
    const html = markdownToHtml(text);
    const ok = await copyRichText(text, html);
    setToast(
      ok
        ? `Copied all ${sprintVariants.length} Shorts.`
        : "Copy failed — try selecting & copying manually."
    );
    if (ok) {
      apiClient.post("/activity/log", {
        type: "script_copied",
        detail: { mode: "sprint", variant_count: sprintVariants.length },
      }).catch(() => {});
    }
  };

  const useInStudio = () => {
    if (!output?.text) return;
    sendToStudio(output);
  };

  // Per-platform Send-to-Studio for the compare-all view. Lets the user pick
  // their winner after A/B-ing all three platforms side-by-side without
  // having to leave compare-mode and switch tabs first.
  const sendToStudio = (jobOutput) => {
    if (!jobOutput?.text) return;
    const narration = extractNarration(jobOutput.text);
    const brollPrompts = extractBrollPrompts(jobOutput.text);
    const handoff = {
      script: narration,
      brollPrompts,
      sourceMode: jobOutput.mode,
      topic: jobOutput.topic,
      platform: jobOutput.platform,
      ts: Date.now(),
    };
    try {
      localStorage.setItem("f48_handoff_script", JSON.stringify(handoff));
    } catch {}
    apiClient.post("/activity/log", {
      type: "script_sent_to_studio",
      detail: {
        script_id: jobOutput.id,
        mode: jobOutput.mode,
        platform: jobOutput.platform,
        broll_prompts: brollPrompts.length,
      },
    }).catch(() => {});
    nav("/studio");
  };

  const loadFromHistory = async (id) => {
    try {
      const r = await apiClient.get(`/scripts/job/${id}`);
      setOutput(r.data);
      setMultiJobs([]);
      setCompareAll(false);
      setStep(STEPS.RESULT);
      apiClient.post("/activity/log", {
        type: "script_opened_from_history",
        detail: { script_id: id, mode: r.data?.mode },
      }).catch(() => {});
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
    setCompareAll(false);
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
  else ctaCopy = "Show me 5 angles →";

  return (
    <main
      className={`studio-main scripts-main ${shortsMode ? "is-shorts" : "is-long"}`}
      data-mode={mode}
      data-platform={platformId}
      data-testid="scripts-page"
    >
      <Toast message={toast} onDismiss={() => setToast("")} />

      {/* v1.8.0 — Sticky results nav: appears whenever there's output, mirrors
          the Netlify Script Engine update so users see the same toolbar on both
          builds. Provides quick-jump anchors, copy actions, and the global
          Collapse/Expand toggle that drives every section's open/closed state. */}
      {step === STEPS.RESULT && output?.text && (() => {
        const isSprint = output.mode === "sprint";
        const isShorts = output.mode === "shorts";
        const isLong = output.mode === "long";
        const hasShorts = isSprint && sprintVariants.length > 0;
        const hasScript = isLong || isShorts;
        const isStreaming = output.status === "running";
        let status;
        if (isStreaming) {
          status = currentStreamingPhase(output.text, output.mode);
        } else if (isSprint) {
          status = sprintVariants.length
            ? `Sprint ready · ${sprintVariants.length} Shorts`
            : "Sprint ready";
        } else if (isShorts) {
          status = "Short ready";
        } else {
          status = "Script ready";
        }
        return (
          <ResultsNavBar
            status={status}
            hasScript={hasScript}
            hasShorts={hasShorts}
            shortsCount={sprintVariants.length}
            allCollapsed={allCollapsed}
            onJumpScript={jumpToScript}
            onJumpShorts={jumpToShorts}
            onCopyScript={copyAll}
            onCopyAllShorts={copyAllShorts}
            onToggleCollapseAll={toggleCollapseAll}
            onStartNew={startOver}
            newCtaLabel={
              isSprint
                ? "New sprint"
                : isShorts
                ? "New short"
                : "New script"
            }
          />
        );
      })()}

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
          className={`mode-opt ${mode === MODES.SHORTS ? "is-active" : ""} ${!hasShortsEntitlement ? "is-locked" : ""}`}
          data-testid="scripts-mode-shorts"
          onClick={() => onModeChange(MODES.SHORTS)}
          title={hasShortsEntitlement ? "" : "Upgrade to unlock Shorts"}
        >
          {hasShortsEntitlement ? <Smartphone size={14} /> : <Lock size={14} />} Shorts
        </button>
      </div>

      {/* Shorts paywall — render inline (in place of the form) when a
          non-entitled user clicks the Shorts mode pill. This lets them
          discover what they'd unlock without surprising them with a 403
          mid-generation. Backend also enforces via _require_entitlement. */}
      {mode === MODES.SHORTS && !hasShortsEntitlement && (
        <EntitlementPaywall feature="shorts" />
      )}

      {/* Step 1: topic + length/platform — hidden when paywall is visible */}
      {mode === MODES.SHORTS && !hasShortsEntitlement ? null : (step === STEPS.TOPIC || step === STEPS.ANGLES) && (
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
              <div className="include-toggles" data-testid="include-toggles">
                <label className="include-toggle">
                  <input
                    type="checkbox"
                    checked={includeHooks}
                    onChange={(e) => setIncludeHooks(e.target.checked)}
                    data-testid="toggle-include-hooks"
                  />
                  <span className="include-track"><span className="include-thumb" /></span>
                  <span>Include hook variations</span>
                </label>
                <label className="include-toggle">
                  <input
                    type="checkbox"
                    checked={includeBroll}
                    onChange={(e) => setIncludeBroll(e.target.checked)}
                    data-testid="toggle-include-broll"
                  />
                  <span className="include-track"><span className="include-thumb" /></span>
                  <span>Include B-roll shot list</span>
                </label>
                <label className="include-toggle">
                  <input
                    type="checkbox"
                    checked={includeProductionNotes}
                    onChange={(e) => setIncludeProductionNotes(e.target.checked)}
                    data-testid="toggle-include-production-notes"
                  />
                  <span className="include-track"><span className="include-thumb" /></span>
                  <span>Include production notes</span>
                </label>
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

          {/* Drip status banner — only while streaming. Shows which section
              Claude is currently writing, plus elapsed seconds. */}
          {output.status === "running" && (
            <div className="drip-status" data-testid="drip-status">
              <span className="drip-spinner" />
              <span>{currentStreamingPhase(output.text, output.mode)}</span>
              <span className="drip-elapsed">{elapsed}s</span>
            </div>
          )}

          {/* Multi-platform tabs + compare-all toggle. When ≥2 platform jobs
              are complete, the user can switch from the single-phone tab view
              to a side-by-side trio comparing all three platforms at once. */}
          {multiJobs.length > 0 && (
            <div className="platform-tabs-row">
              <div className="platform-tabs" data-testid="platform-tabs">
                {multiJobs.map((j) => {
                  const p = PLATFORMS.find((x) => x.id === j.platform);
                  return (
                    <button
                      key={j.platform}
                      type="button"
                      className={`platform-tab ${!compareAll && activeTab === j.platform ? "is-active" : ""}`}
                      data-testid={`platform-tab-${j.platform}`}
                      style={{ "--tab-accent": p?.accent }}
                      onClick={() => {
                        setCompareAll(false);
                        switchTab(j.platform);
                      }}
                    >
                      <span className={`platform-tab-status is-${j.status}`} />
                      {p?.label || j.platform}
                    </button>
                  );
                })}
              </div>
              {multiJobs.filter((j) => j.status === "complete").length >= 2 && (
                <button
                  type="button"
                  className={`compare-all-btn ${compareAll ? "is-active" : ""}`}
                  data-testid="compare-all-btn"
                  onClick={() => setCompareAll((v) => !v)}
                  title="View all platforms side-by-side"
                >
                  <Layers size={13} />
                  {compareAll ? "Single view" : "Compare all"}
                </button>
              )}
            </div>
          )}

          {/* Compare-all view: render every completed platform's phone +
              short-form script side-by-side. Each phone scopes its own
              --platform-accent locally so all three rims render in their
              correct color simultaneously. */}
          {compareAll && multiJobs.length > 0 ? (
            <div className="compare-grid" data-testid="compare-grid">
              {multiJobs
                .filter((j) => j.status === "complete" && j.output?.text)
                .map((j) => {
                  const p = PLATFORMS.find((x) => x.id === j.platform);
                  const jobSections = parseSections(j.output.text);
                  return (
                    <div
                      key={j.platform}
                      className="compare-cell"
                      data-testid={`compare-cell-${j.platform}`}
                      style={{ "--platform-accent": p?.accent }}
                    >
                      <div className="compare-cell-head">
                        <span
                          className="compare-cell-dot"
                          style={{ background: p?.accent }}
                        />
                        <span className="compare-cell-label">
                          {p?.label || j.platform}
                        </span>
                      </div>
                      <PhoneFrame platform={j.platform}>
                        <ShortPhoneBody
                          shortBody={jobSections.shortScript?.body || ""}
                        />
                      </PhoneFrame>
                      <button
                        type="button"
                        className="compare-cell-cta"
                        data-testid={`compare-send-to-studio-${j.platform}`}
                        onClick={() => sendToStudio(j.output)}
                        title={`Send the ${p?.label || j.platform} script to Studio`}
                      >
                        <Sparkles size={12} /> Send to Studio
                      </button>
                    </div>
                  );
                })}
            </div>
          ) : output.mode === "sprint" ? (
            <SprintResult
              variants={sprintVariants}
              platform={output.platform || platform}
              onPromote={promoteVariant}
              promotingIndex={promotingIndex}
              onCopyAll={copyAllShorts}
            />
          ) : output.mode === "shorts" ? (
            <div className="shorts-bento" data-testid="shorts-layout">
              {/* HERO — phone preview anchored at top center */}
              <div id="shorts-script-column" className="shorts-bento-hero">
                <PhoneFrame platform={output.platform || platform}>
                  <ShortPhoneBody shortBody={sections.shortScript?.body || ""} />
                </PhoneFrame>
              </div>
              {/* BENTO GRID — pinned row first (Hook Variations, Caption, B-Roll Shot List),
                  then everything else flows below. Cards auto-balance by spanning rows
                  in the 3-col grid; on mobile they stack 1-col under the phone. */}
              <div className="shorts-bento-grid">
                {sections.hooks && (
                  <SectionCard
                    keyName="hooks"
                    section={sections.hooks}
                    testid="section-hooks"
                    revealIndex={0}
                    collapsed={collapsedSections.has("hooks")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.caption && (
                  <SectionCard
                    keyName="caption"
                    section={sections.caption}
                    testid="section-caption"
                    revealIndex={1}
                    collapsed={collapsedSections.has("caption")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.broll && (
                  <SectionCard
                    keyName="broll"
                    section={sections.broll}
                    testid="section-broll"
                    revealIndex={2}
                    collapsed={collapsedSections.has("broll")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.hashtags && (
                  <SectionCard
                    keyName="hashtags"
                    section={sections.hashtags}
                    testid="section-hashtags"
                    revealIndex={3}
                    collapsed={collapsedSections.has("hashtags")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.onScreen && (
                  <SectionCard
                    keyName="onScreen"
                    section={sections.onScreen}
                    testid="section-onScreen"
                    revealIndex={4}
                    collapsed={collapsedSections.has("onScreen")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.titleVariants && (
                  <SectionCard
                    keyName="titleVariants"
                    section={sections.titleVariants}
                    testid="section-titleVariants"
                    revealIndex={5}
                    collapsed={collapsedSections.has("titleVariants")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.coverPrompts && (
                  <SectionCard
                    keyName="coverPrompts"
                    section={sections.coverPrompts}
                    testid="section-coverPrompts"
                    revealIndex={6}
                    collapsed={collapsedSections.has("coverPrompts")}
                    onToggle={toggleSection}
                  />
                )}
                {sections.notes && (
                  <SectionCard
                    keyName="notes"
                    section={sections.notes}
                    testid="section-notes"
                    revealIndex={7}
                    collapsed={collapsedSections.has("notes")}
                    onToggle={toggleSection}
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
                  collapsed={collapsedSections.has(k)}
                  onToggle={toggleSection}
                />
              ) : null
            )
          )}
        </div>
      )}

      <ScriptHistoryList
        history={history}
        currentMode={mode}
        onOpen={loadFromHistory}
        onDelete={deleteFromHistory}
      />
    </main>
  );
}
