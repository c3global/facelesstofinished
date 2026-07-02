import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ImageIcon, Sparkles, Wand2, Loader2, Trash2, Download, RefreshCw,
  Zap, Crown, Lock, Copy as CopyIcon, Layers, Check, Maximize2, X,
} from "lucide-react";
import { apiClient } from "../App";

/**
 * Standalone Thumbnail Engine — accessible at /thumbnails.
 *
 * Two image-gen engines (Premium = OpenAI gpt-image-1, Fast = Gemini Nano
 * Banana), three aspect ratios (16:9 / 9:16 / 1:1), an optional Claude-powered
 * prompt rewriter, and a 60-item history grid. This page is intentionally
 * self-contained so it can ship without breaking the Studio/Scripts flows.
 *
 * Quota:
 *   - T3 / T4 / Founder: unlimited
 *   - T2: 50/mo Fast or Premium
 *   - T1: 20/mo Fast only (Premium 402s with a friendly upgrade prompt)
 */

const ENGINES = [
  {
    id: "premium",
    label: "Premium",
    sub: "OpenAI gpt-image-1 · highest fidelity",
    Icon: Crown,
  },
  {
    id: "fast",
    label: "Fast",
    sub: "Gemini Nano Banana · quick A/B testing",
    Icon: Zap,
  },
];

const ASPECTS = [
  { id: "16_9", label: "16:9", sub: "YouTube" },
  { id: "9_16", label: "9:16", sub: "Shorts / Reels / TikTok" },
  { id: "1_1",  label: "1:1",  sub: "Instagram feed" },
];

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function friendlyError(e) {
  const status = e?.response?.status;
  const detail = e?.response?.data?.detail;
  // 402 = quota / paywall — show the backend's message verbatim.
  if (status === 402 && detail?.message) return detail.message;
  // 502 / 503 / 504 = upstream gateway hiccup (Cloudflare ↔ origin). The
  // raw "origin web server returned an invalid response" copy is scary
  // and inaccurate from the user's perspective — they didn't break
  // anything. Replace with a warm, retry-positive message. Also handle
  // the case where Cloudflare returned an HTML error page (no JSON body).
  if (status === 502 || status === 503 || status === 504) {
    return "Our render server is warming back up (likely from a deploy). Give it ~30 seconds and try again — your prompt is still here.";
  }
  // Network-level error (no response at all, e.g. timeout / DNS / CORS).
  if (e?.code === "ECONNABORTED" || e?.message?.includes("Network Error") || !e?.response) {
    return "Couldn't reach the render server. Check your connection and try again — your prompt is preserved.";
  }
  if (typeof detail === "string") {
    // FastAPI sometimes leaks Cloudflare HTML through detail; sniff and swap.
    if (detail.includes("origin web server") || detail.includes("Cloudflare")) {
      return "Our render server is warming back up. Give it ~30 seconds and try again.";
    }
    return detail;
  }
  if (detail?.message) return detail.message;
  return e?.message || "Something went wrong. Please try again.";
}

export default function Thumbnails() {
  const [engine, setEngine] = useState("premium");
  const [aspect, setAspect] = useState("16_9");
  const [prompt, setPrompt] = useState("");
  const [topic, setTopic] = useState("");
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [batchStatus, setBatchStatus] = useState(null);  // {current, total} when generating all 3
  const [rewriting, setRewriting] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [quota, setQuota] = useState(null);

  // ---- Cover-prompt picker state (v1.10.1) ----
  // When the user arrives from Scripts via "Make thumbnail", we may receive a
  // list of pre-written cover prompts (one per title variant). User can pick
  // one OR fire "Generate all" which renders all 3 in sequence.
  const [coverChoices, setCoverChoices] = useState([]);
  const [selectedChoiceIndex, setSelectedChoiceIndex] = useState(null);
  const [confirmBatch, setConfirmBatch] = useState(false);

  // Lightbox state — when set, renders a full-screen modal preview of the
  // selected thumbnail. Closes on backdrop click or ESC.
  const [lightboxThumb, setLightboxThumb] = useState(null);

  useEffect(() => {
    if (!lightboxThumb) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setLightboxThumb(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lightboxThumb]);

  const flashToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3500);
  };

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const r = await apiClient.get("/thumbnails");
      setHistory(r.data?.thumbnails || []);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const loadQuota = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/quota");
      setQuota(r.data);
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => { loadHistory(); loadQuota(); }, [loadHistory, loadQuota]);

  // ---- Handoff pickup (v1.10.1) ----
  // When a user lands here from Scripts via "Make thumbnail", the Scripts
  // page stashes the script topic + an optional list of cover-prompt
  // choices in localStorage. Read it once on mount, populate state, and
  // clear so a manual revisit doesn't re-populate stale data.
  useEffect(() => {
    let raw = null;
    try { raw = localStorage.getItem("f48_handoff_thumbnail"); } catch { return; }
    if (!raw) return;
    try {
      const handoff = JSON.parse(raw);
      if (handoff?.topic) setTopic((cur) => cur || handoff.topic);

      // Default aspect to 16:9 for long-form scripts, 9:16 for shorts/sprint
      // so the user doesn't have to flip it after handoff. Override their
      // last manual selection only on first arrival.
      if (handoff?.mode === "long") setAspect("16_9");
      else if (handoff?.mode === "shorts" || handoff?.mode === "sprint") setAspect("9_16");

      // Path A — script has 3 picked-apart cover prompts → show the picker.
      if (Array.isArray(handoff?.choices) && handoff.choices.length > 0) {
        setCoverChoices(handoff.choices);
        // Auto-select the first option so the prompt textarea has content
        // — keeps "Generate thumbnail" enabled even if the user doesn't click
        // a chip first. They can click another chip to swap.
        setSelectedChoiceIndex(handoff.choices[0].index);
        setPrompt(handoff.choices[0].prompt);
        flashToast("Pick one of the 3 cover concepts below — or hit 'Generate all 3' to compare.");
      } else if (handoff?.seed) {
        // Path B — legacy script (no cover prompts) → drop in narration seed.
        setPrompt((cur) => cur || handoff.seed);
        flashToast("Pre-filled from your script — rewrite or edit as needed.");
      }
    } catch { /* malformed; ignore */ }
    try { localStorage.removeItem("f48_handoff_thumbnail"); } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the user clicks a cover-prompt chip, swap the textarea content
  // and remember which one they picked so the chip highlights visually.
  const pickCoverChoice = (choice) => {
    setSelectedChoiceIndex(choice.index);
    setPrompt(choice.prompt);
    setError("");
  };

  // When the quota response says Premium is locked, the user dropped to a
  // tier that doesn't include it. Bounce them to Fast automatically so they
  // can keep generating without a confusing 402 the moment they click.
  useEffect(() => {
    if (quota && !quota.unlimited && quota.thumbnail_premium_allowed === false && engine === "premium") {
      setEngine("fast");
    }
  }, [quota, engine]);

  const onRewrite = async () => {
    if (!prompt.trim() || rewriting) return;
    setError("");
    setRewriting(true);
    try {
      const r = await apiClient.post("/thumbnails/rewrite-prompt", {
        raw_prompt: prompt.trim(),
        topic: topic.trim() || undefined,
      });
      const rewritten = r.data?.rewritten_prompt || "";
      if (rewritten) {
        setPrompt(rewritten);
        flashToast("Prompt rewritten — feel free to tweak it before generating.");
      }
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setRewriting(false);
    }
  };

  const onGenerate = async () => {
    const trimmed = prompt.trim();
    if (trimmed.length < 4 || generating) return;
    setError("");
    setGenerating(true);
    try {
      const r = await apiClient.post("/thumbnails/generate", {
        prompt: trimmed,
        engine,
        aspect,
      }, { timeout: 120_000 });
      setHistory((prev) => [r.data, ...prev]);
      loadQuota();
      flashToast(`${engine === "premium" ? "Premium" : "Fast"} thumbnail ready.`);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setGenerating(false);
    }
  };

  // ---- Generate-all flow (v1.10.1) ----
  // Fires the 3 cover prompts SEQUENTIALLY (not in parallel) so gpt-image-1's
  // rate limit doesn't trip and the user sees thumbnails populate one by one
  // in the history grid. Each individual failure surfaces as an inline error
  // but doesn't stop the remaining renders — partial success is better than
  // none. The cost-confirmation modal gates this for non-unlimited tiers
  // since 3 slots is a meaningful chunk of the monthly quota.
  const generateAll = async () => {
    if (!coverChoices.length || batchStatus) return;
    const isUnlimited = !!(quota?.unlimited);
    if (!isUnlimited && !confirmBatch) {
      setConfirmBatch(true);
      return;
    }
    setConfirmBatch(false);
    setError("");
    setGenerating(true);
    const successes = [];
    const failures = [];
    for (let i = 0; i < coverChoices.length; i++) {
      setBatchStatus({ current: i + 1, total: coverChoices.length });
      try {
        const r = await apiClient.post("/thumbnails/generate", {
          prompt: coverChoices[i].prompt,
          engine,
          aspect,
        }, { timeout: 120_000 });
        setHistory((prev) => [r.data, ...prev]);
        successes.push(r.data);
      } catch (e) {
        failures.push({ idx: i + 1, msg: friendlyError(e) });
        // If we hit a quota wall mid-batch, stop instead of burning more
        // slots that will all 402. Other failure types we keep going.
        if (e?.response?.status === 402) break;
      }
    }
    setBatchStatus(null);
    setGenerating(false);
    loadQuota();

    if (successes.length === coverChoices.length) {
      flashToast(`All ${successes.length} thumbnails ready — pick your favorite.`);
    } else if (successes.length > 0) {
      const failMsg = failures.length === 1
        ? failures[0].msg
        : `${failures.length} variants failed.`;
      setError(`${successes.length} of ${coverChoices.length} succeeded. ${failMsg}`);
    } else {
      setError(failures[0]?.msg || "All variants failed. Please try again.");
    }
  };

  const onDelete = async (id) => {
    try {
      await apiClient.delete(`/thumbnails/${id}`);
      setHistory((prev) => prev.filter((t) => t.id !== id));
      flashToast("Thumbnail deleted.");
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  const onCopyPrompt = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      flashToast("Prompt copied to clipboard.");
    } catch {
      flashToast("Couldn't copy — please copy manually.");
    }
  };

  const onDownload = async (thumb) => {
    try {
      const r = await apiClient.get(thumb.url.replace(/^\/api/, ""), { responseType: "blob" });
      const blob = new Blob([r.data], { type: "image/png" });
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = `f2f48-thumbnail-${thumb.id}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(objUrl);
    } catch {
      flashToast("Couldn't download — right-click → Save Image As instead.");
    }
  };

  // Premium might be locked behind a tier — show a small lock + label rather
  // than hiding the button (preserves the upgrade conversion path).
  const premiumLocked = !!(quota && !quota.unlimited && quota.thumbnail_premium_allowed === false);

  const quotaPill = useMemo(() => {
    if (!quota) return null;
    if (quota.unlimited) {
      return (
        <span className="thumb-quota thumb-quota-unlimited" data-testid="thumb-quota-pill">
          <Crown size={12} />
          <span>{quota.tier_label || "Unlimited"} · unlimited</span>
        </span>
      );
    }
    const used = quota.thumbnails_used ?? 0;
    const total = quota.thumbnails_total ?? 0;
    const remaining = quota.thumbnails_remaining ?? Math.max(0, total - used);
    const low = total > 0 && remaining <= Math.max(1, Math.ceil(total * 0.2));
    return (
      <span
        className={`thumb-quota ${remaining === 0 ? "is-exhausted" : low ? "is-low" : ""}`}
        data-testid="thumb-quota-pill"
      >
        <Zap size={12} />
        <span>{used} of {total} thumbnails</span>
      </span>
    );
  }, [quota]);

  return (
    <main className="thumbnails-main" data-testid="thumbnails-page">
      <div className="studio-hero">
        <div className="studio-hero-top">
          <p className="studio-eyebrow" data-testid="thumbnails-eyebrow">
            Thumbnail Engine · v1
          </p>
          {quotaPill}
        </div>
        <h1 className="studio-title">Click-worthy thumbnails in seconds.</h1>
        <p className="studio-sub">
          Describe the cover you want. Pick Premium for hero thumbnails or Fast for quick A/B testing. Aspect ratios for YouTube, Shorts, and the gram.
        </p>
      </div>

      <section className="thumb-card" data-testid="thumb-composer">
        {coverChoices.length > 0 && (
          <div className="thumb-picker" data-testid="thumb-cover-picker">
            <div className="thumb-picker-head">
              <span className="thumb-label">
                <Layers size={11} /> Cover concepts from your script
              </span>
              <button
                type="button"
                className="thumb-genall-btn"
                onClick={generateAll}
                disabled={generating || !!batchStatus}
                data-testid="thumb-generate-all-btn"
                title="Generate one thumbnail per concept and pick your favorite"
              >
                {batchStatus ? (
                  <>
                    <Loader2 size={13} className="thumb-spin" />
                    Generating {batchStatus.current} of {batchStatus.total}…
                  </>
                ) : (
                  <>
                    <Sparkles size={13} /> Generate all {coverChoices.length}
                  </>
                )}
              </button>
            </div>
            <div className="thumb-picker-grid">
              {coverChoices.map((c) => {
                const active = selectedChoiceIndex === c.index;
                return (
                  <button
                    type="button"
                    key={c.index}
                    className={`thumb-choice ${active ? "is-active" : ""}`}
                    onClick={() => pickCoverChoice(c)}
                    data-testid={`thumb-choice-${c.index}`}
                  >
                    <div className="thumb-choice-head">
                      <span className="thumb-choice-num">{c.index}</span>
                      {c.label && <span className="thumb-choice-label">{c.label}</span>}
                      {active && <Check size={13} className="thumb-choice-check" />}
                    </div>
                    {c.title && (
                      <div className="thumb-choice-title">{c.title}</div>
                    )}
                    <div className="thumb-choice-prompt">{c.prompt}</div>
                  </button>
                );
              })}
            </div>
            <p className="thumb-picker-hint">
              Pick one to load it into the editor below, or hit{" "}
              <b>Generate all {coverChoices.length}</b> to render every concept and compare.
            </p>
          </div>
        )}

        <div className="thumb-row">
          <label className="thumb-label" htmlFor="thumb-topic">
            Script topic <span className="thumb-optional">(optional)</span>
          </label>
          <input
            id="thumb-topic"
            data-testid="thumb-topic"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="What's the video actually about? — helps the rewriter."
            maxLength={300}
          />
        </div>

        <div className="thumb-row">
          <label className="thumb-label" htmlFor="thumb-prompt">
            Thumbnail prompt
          </label>
          <textarea
            id="thumb-prompt"
            data-testid="thumb-prompt"
            rows={5}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="A confident woman in business attire on a rooftop at golden hour, glowing city behind her, dramatic lighting…"
            maxLength={2000}
          />
          <div className="thumb-prompt-meta">
            <button
              type="button"
              className="thumb-rewrite-btn"
              onClick={onRewrite}
              disabled={!prompt.trim() || rewriting}
              data-testid="thumb-rewrite-btn"
              title="Rewrite into a punchier, more visual prompt"
            >
              {rewriting ? <Loader2 size={13} className="thumb-spin" /> : <Wand2 size={13} />}
              {rewriting ? "Rewriting…" : "Rewrite for me"}
            </button>
            <span className="thumb-char-count">{prompt.length} / 2000</span>
          </div>
        </div>

        <div className="thumb-row thumb-row-double">
          <div className="thumb-control-group">
            <span className="thumb-label">Engine</span>
            <div className="thumb-segmented" role="radiogroup" aria-label="Engine">
              {ENGINES.map((opt) => {
                const Icon = opt.Icon;
                const locked = opt.id === "premium" && premiumLocked;
                const active = engine === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    className={`thumb-seg ${active ? "is-active" : ""} ${locked ? "is-locked" : ""}`}
                    onClick={() => !locked && setEngine(opt.id)}
                    disabled={locked}
                    data-testid={`thumb-engine-${opt.id}`}
                    title={locked ? "Premium is part of the Scripts + Shorts tier and up — upgrade to unlock" : opt.sub}
                  >
                    {locked ? <Lock size={13} /> : <Icon size={13} />}
                    <span className="thumb-seg-label">{opt.label}</span>
                    <span className="thumb-seg-sub">{opt.sub}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="thumb-control-group">
            <span className="thumb-label">Aspect</span>
            <div className="thumb-segmented" role="radiogroup" aria-label="Aspect ratio">
              {ASPECTS.map((opt) => {
                const active = aspect === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    className={`thumb-seg ${active ? "is-active" : ""}`}
                    onClick={() => setAspect(opt.id)}
                    data-testid={`thumb-aspect-${opt.id}`}
                  >
                    <span className="thumb-seg-label">{opt.label}</span>
                    <span className="thumb-seg-sub">{opt.sub}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="thumb-actions">
          <button
            type="button"
            className="thumb-generate-btn"
            onClick={onGenerate}
            disabled={prompt.trim().length < 4 || generating}
            data-testid="thumb-generate-btn"
          >
            {generating ? <Loader2 size={15} className="thumb-spin" /> : <Sparkles size={15} />}
            {generating ? "Generating — takes 20-60s…" : "Generate thumbnail"}
          </button>
        </div>

        {error && (
          <div className="thumb-error" data-testid="thumb-error">{error}</div>
        )}
        {toast && (
          <div className="thumb-toast" data-testid="thumb-toast">{toast}</div>
        )}
      </section>

      <section className="thumb-history" data-testid="thumb-history">
        <div className="thumb-history-head">
          <h2 className="thumb-history-title">
            <ImageIcon size={16} /> Recent thumbnails
          </h2>
          <button
            type="button"
            className="thumb-refresh-btn"
            onClick={loadHistory}
            disabled={loadingHistory}
            data-testid="thumb-history-refresh"
            aria-label="Refresh"
          >
            <RefreshCw size={14} className={loadingHistory ? "thumb-spin" : ""} />
          </button>
        </div>

        {loadingHistory && history.length === 0 && (
          <div className="thumb-empty">Loading…</div>
        )}
        {!loadingHistory && history.length === 0 && (
          <div className="thumb-empty">
            Your generated thumbnails will appear here. Try the rewriter for an inspired prompt.
          </div>
        )}

        {history.length > 0 && (
          <div className="thumb-grid">
            {history.map((t) => (
              <article
                key={t.id}
                className={`thumb-tile thumb-tile-${t.aspect}`}
                data-testid={`thumb-tile-${t.id}`}
              >
                <div className="thumb-tile-img-wrap">
                  <button
                    type="button"
                    className="thumb-tile-img-btn"
                    onClick={() => setLightboxThumb(t)}
                    data-testid={`thumb-open-lightbox-${t.id}`}
                    title="Click to enlarge"
                    aria-label="Enlarge thumbnail"
                  >
                    <img
                      src={t.url}
                      alt={t.original_prompt || "Generated thumbnail"}
                      className="thumb-tile-img"
                      loading="lazy"
                    />
                    <span className="thumb-tile-zoom-hint" aria-hidden="true">
                      <Maximize2 size={14} />
                    </span>
                  </button>
                  <div className="thumb-tile-overlay">
                    <button
                      type="button"
                      className="thumb-tile-action"
                      onClick={() => onDownload(t)}
                      data-testid={`thumb-download-${t.id}`}
                      title="Download PNG"
                    >
                      <Download size={14} />
                    </button>
                    <button
                      type="button"
                      className="thumb-tile-action"
                      onClick={() => onCopyPrompt(t.original_prompt || t.prompt)}
                      data-testid={`thumb-copy-${t.id}`}
                      title="Copy prompt"
                    >
                      <CopyIcon size={14} />
                    </button>
                    <button
                      type="button"
                      className="thumb-tile-action thumb-tile-action-danger"
                      onClick={() => onDelete(t.id)}
                      data-testid={`thumb-delete-${t.id}`}
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
                <div className="thumb-tile-meta">
                  <span className={`thumb-tile-engine thumb-tile-engine-${t.engine}`}>
                    {t.engine === "premium" ? "Premium" : "Fast"}
                  </span>
                  <span className="thumb-tile-aspect">{t.aspect.replace("_", ":")}</span>
                  <span className="thumb-tile-date">{fmtDate(t.created_at)}</span>
                </div>
                <p className="thumb-tile-prompt" title={t.original_prompt}>
                  {t.original_prompt || t.prompt}
                </p>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Cost-confirmation modal for "Generate all 3" on paid quota-bound
          tiers. Founders / owner / studio-grant bypass this entirely
          (generateAll fires immediately for unlimited users). */}
      {confirmBatch && (
        <div
          className="thumb-modal-backdrop"
          onClick={() => setConfirmBatch(false)}
          data-testid="thumb-confirm-backdrop"
        >
          <div
            className="thumb-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="thumb-confirm-title"
            data-testid="thumb-confirm-modal"
          >
            <h3 id="thumb-confirm-title" className="thumb-modal-title">
              Generate all {coverChoices.length} variants?
            </h3>
            <p className="thumb-modal-body">
              This will use <b>{coverChoices.length} thumbnails</b> from your
              current cycle —
              {quota?.thumbnails_remaining !== undefined && (
                <> you'll have <b>{Math.max(0, (quota.thumbnails_remaining ?? 0) - coverChoices.length)}</b> left after.</>
              )}
              {" "}You can delete the ones you don't like afterwards.
            </p>
            <div className="thumb-modal-actions">
              <button
                type="button"
                className="thumb-modal-btn"
                onClick={() => setConfirmBatch(false)}
                data-testid="thumb-confirm-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                className="thumb-modal-btn thumb-modal-btn-primary"
                onClick={generateAll}
                data-testid="thumb-confirm-proceed"
              >
                <Sparkles size={13} /> Generate all {coverChoices.length}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Full-screen lightbox preview. Click outside the image, hit ESC, or
          press the X to dismiss. Action buttons (Download / Copy prompt) are
          duplicated here so users don't have to close + re-aim at the tile. */}
      {lightboxThumb && (
        <div
          className="thumb-lightbox-backdrop"
          onClick={() => setLightboxThumb(null)}
          data-testid="thumb-lightbox-backdrop"
        >
          <button
            type="button"
            className="thumb-lightbox-close"
            onClick={(e) => { e.stopPropagation(); setLightboxThumb(null); }}
            aria-label="Close preview"
            data-testid="thumb-lightbox-close"
          >
            <X size={20} />
          </button>
          <figure
            className={`thumb-lightbox thumb-lightbox-${lightboxThumb.aspect}`}
            onClick={(e) => e.stopPropagation()}
            data-testid="thumb-lightbox"
          >
            <img
              src={lightboxThumb.url}
              alt={lightboxThumb.original_prompt || "Thumbnail preview"}
              className="thumb-lightbox-img"
              data-testid="thumb-lightbox-img"
            />
            <figcaption className="thumb-lightbox-caption">
              <div className="thumb-lightbox-meta">
                <span className={`thumb-tile-engine thumb-tile-engine-${lightboxThumb.engine}`}>
                  {lightboxThumb.engine === "premium" ? "Premium" : "Fast"}
                </span>
                <span className="thumb-tile-aspect">{lightboxThumb.aspect.replace("_", ":")}</span>
                <span className="thumb-tile-date">{fmtDate(lightboxThumb.created_at)}</span>
              </div>
              <p className="thumb-lightbox-prompt">{lightboxThumb.original_prompt || lightboxThumb.prompt}</p>
              <div className="thumb-lightbox-actions">
                <button
                  type="button"
                  className="thumb-lightbox-btn"
                  onClick={() => onDownload(lightboxThumb)}
                  data-testid="thumb-lightbox-download"
                >
                  <Download size={14} /> Download
                </button>
                <button
                  type="button"
                  className="thumb-lightbox-btn"
                  onClick={() => onCopyPrompt(lightboxThumb.original_prompt || lightboxThumb.prompt)}
                  data-testid="thumb-lightbox-copy"
                >
                  <CopyIcon size={14} /> Copy prompt
                </button>
              </div>
            </figcaption>
          </figure>
        </div>
      )}
    </main>
  );
}
