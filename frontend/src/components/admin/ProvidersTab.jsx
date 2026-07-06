import React, { useEffect, useState } from "react";
import { apiClient } from "../../App";
import { Save, Zap, ZapOff, ShieldCheck, AlertTriangle, RotateCcw } from "lucide-react";

// Admin Providers tab — control fal.ai kill switch + stock-first defaults.
// Reads/writes /api/admin/system/faceless-config. The Studio UI hydrates
// from the public /api/config/faceless endpoint on mount, so any change
// here takes effect on the next Studio page load (or reload).
export default function ProvidersTab() {
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [flash, setFlash] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const r = await apiClient.get("/admin/system/faceless-config");
      setCfg(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to load config");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setErr("");
    setFlash("");
    try {
      const r = await apiClient.put("/admin/system/faceless-config", {
        fal_ai_enabled: !!cfg.fal_ai_enabled,
        ai_visuals_enabled: !!cfg.ai_visuals_enabled,
        default_broll_source: cfg.default_broll_source || "pexels",
        max_ai_scenes_per_render: Number(cfg.max_ai_scenes_per_render) || 0,
        max_ai_renders_per_user_day: Number(cfg.max_ai_renders_per_user_day) || 0,
      });
      setCfg(r.data);
      setFlash("Saved — takes effect on the next Studio page load.");
      setTimeout(() => setFlash(""), 4000);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading || !cfg) {
    return <div className="admin-loading" data-testid="providers-loading">Loading providers config…</div>;
  }

  return (
    <div className="providers-tab" data-testid="providers-tab">
      <div className="providers-header">
        <div>
          <h2 className="providers-title">Faceless Studio providers</h2>
          <p className="providers-sub">
            Global fal.ai kill switch, stock-first defaults, and per-user AI caps.
            Changes are activity-logged and take effect on the next Studio page load.
          </p>
        </div>
        {cfg.updated_at && (
          <div className="providers-meta">
            <div>Last updated {new Date(cfg.updated_at).toLocaleString()}</div>
            {cfg.updated_by && <div>by {cfg.updated_by}</div>}
          </div>
        )}
      </div>

      {err && <div className="providers-error" data-testid="providers-error">{err}</div>}
      {flash && <div className="providers-flash" data-testid="providers-flash">{flash}</div>}

      <div className="providers-grid">
        {/* fal.ai kill switch */}
        <div className="providers-card">
          <div className="providers-card-head">
            {cfg.fal_ai_enabled ? <Zap size={16} color="#F5D9B6" /> : <ZapOff size={16} color="#9AA5B8" />}
            <div className="providers-card-title">fal.ai (Kling / Veo / Pika / Flux)</div>
          </div>
          <p className="providers-card-body">
            Global toggle for platform-billed fal.ai calls. When off, every Faceless render
            that requests AI B-roll silently downgrades to the default stock provider.
            Customer BYOK fal.ai keys are <b>not</b> affected — they still work.
          </p>
          <label className="providers-toggle" data-testid="fal-ai-toggle">
            <input
              type="checkbox"
              checked={!!cfg.fal_ai_enabled}
              onChange={(e) => setCfg({ ...cfg, fal_ai_enabled: e.target.checked })}
            />
            <span>{cfg.fal_ai_enabled ? "ENABLED — platform can call fal.ai" : "DISABLED — platform fal.ai blocked"}</span>
          </label>
        </div>

        {/* AI visuals master toggle */}
        <div className="providers-card">
          <div className="providers-card-head">
            <ShieldCheck size={16} color="#BFEFE3" />
            <div className="providers-card-title">AI-generated visuals (all providers)</div>
          </div>
          <p className="providers-card-body">
            Master switch for ANY AI visual generation — includes Nano Banana (Emergent key,
            not fal.ai). Turn this off to force 100% stock/uploaded B-roll only.
          </p>
          <label className="providers-toggle" data-testid="ai-visuals-toggle">
            <input
              type="checkbox"
              checked={!!cfg.ai_visuals_enabled}
              onChange={(e) => setCfg({ ...cfg, ai_visuals_enabled: e.target.checked })}
            />
            <span>{cfg.ai_visuals_enabled ? "ENABLED" : "DISABLED — stock-only mode"}</span>
          </label>
        </div>

        {/* Default source */}
        <div className="providers-card">
          <div className="providers-card-head">
            <div className="providers-card-title">Default B-roll source</div>
          </div>
          <p className="providers-card-body">
            What Faceless Studio uses when the customer doesn&apos;t explicitly pick a source.
            &quot;Mix&quot; auto-splits scenes across Pexels + Pixabay.
          </p>
          <select
            className="providers-select"
            data-testid="default-source-select"
            value={cfg.default_broll_source || "pexels"}
            onChange={(e) => setCfg({ ...cfg, default_broll_source: e.target.value })}
          >
            <option value="pexels">Pexels (free stock)</option>
            <option value="pixabay">Pixabay (free stock)</option>
            <option value="mix">Mix (Pexels + Pixabay)</option>
            <option value="uploaded">Uploaded media only</option>
          </select>
        </div>

        {/* Per-render cap */}
        <div className="providers-card">
          <div className="providers-card-head">
            <AlertTriangle size={16} color="#F5D9B6" />
            <div className="providers-card-title">Max AI scenes per render</div>
          </div>
          <p className="providers-card-body">
            Hard cap. When a script has more scenes than this, the excess auto-fall-back to
            the default stock provider. 0 = block all AI scenes even when explicitly picked.
          </p>
          <input
            type="number" min="0" max="50" className="providers-input"
            data-testid="max-ai-scenes-input"
            value={cfg.max_ai_scenes_per_render}
            onChange={(e) => setCfg({ ...cfg, max_ai_scenes_per_render: e.target.value })}
          />
        </div>

        {/* Per-user daily cap */}
        <div className="providers-card">
          <div className="providers-card-head">
            <AlertTriangle size={16} color="#F5D9B6" />
            <div className="providers-card-title">Max AI renders / user / day</div>
          </div>
          <p className="providers-card-body">
            Per-email daily cap on renders that use any AI source. Excess renders auto-downgrade
            to stock and stamp <code>faceless_ai_downgraded</code> on the Activity feed. 0 = unlimited.
          </p>
          <input
            type="number" min="0" max="1000" className="providers-input"
            data-testid="max-ai-renders-input"
            value={cfg.max_ai_renders_per_user_day}
            onChange={(e) => setCfg({ ...cfg, max_ai_renders_per_user_day: e.target.value })}
          />
        </div>
      </div>

      <div className="providers-actions">
        <button
          className="providers-save"
          onClick={save}
          disabled={saving}
          data-testid="providers-save-btn"
        >
          <Save size={14} /> {saving ? "Saving…" : "Save changes"}
        </button>
        <button
          className="providers-reload"
          onClick={load}
          disabled={saving}
          data-testid="providers-reload-btn"
        >
          <RotateCcw size={14} /> Reload
        </button>
      </div>
    </div>
  );
}
