import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ImageIcon, Sparkles, Wand2, Loader2, Trash2, Download, RefreshCw,
  Zap, Crown, Lock, Copy as CopyIcon,
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
  if (status === 402 && detail?.message) return detail.message;
  if (typeof detail === "string") return detail;
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
  const [rewriting, setRewriting] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [quota, setQuota] = useState(null);

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

  // ---- Handoff pickup (v1.9.0) ----
  // When a user lands here from Scripts via "Make thumbnail", the Scripts
  // page stashes the script topic + opening hook in localStorage. Read it
  // once on mount, pre-fill the inputs, and clear so a manual revisit
  // doesn't re-populate stale data.
  useEffect(() => {
    let raw = null;
    try { raw = localStorage.getItem("f48_handoff_thumbnail"); } catch { return; }
    if (!raw) return;
    try {
      const handoff = JSON.parse(raw);
      if (handoff?.topic) setTopic((cur) => cur || handoff.topic);
      if (handoff?.seed) {
        setPrompt((cur) => cur || handoff.seed);
        flashToast("Pre-filled from your script — rewrite or edit as needed.");
      }
    } catch { /* malformed; ignore */ }
    try { localStorage.removeItem("f48_handoff_thumbnail"); } catch {}
  }, []);

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
                  <img
                    src={t.url}
                    alt={t.original_prompt || "Generated thumbnail"}
                    className="thumb-tile-img"
                    loading="lazy"
                  />
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
    </main>
  );
}
