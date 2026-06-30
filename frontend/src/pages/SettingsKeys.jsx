import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound, ShieldCheck, Trash2, Check, ArrowLeft, ExternalLink } from "lucide-react";
import { apiClient } from "../App";

/**
 * BYOK ("Bring Your Own Key") settings page. T4 / Pro Plus + Founder users
 * can save their own OpenAI / HeyGen / fal.ai keys. Keys are Fernet-
 * encrypted on the backend; the full plaintext is NEVER returned to the
 * client after save (only a masked `sk-…0abc` hint).
 *
 * Customers on lower tiers see an upgrade nudge instead of the form.
 */
export default function SettingsKeys() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState({}); // service -> { value, busy, error, ok }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/user/byok");
      setData(r.data || null);
    } catch (e) {
      setData({ byok_allowed: false, services: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const setSvc = (id, patch) => {
    setDraft((d) => ({ ...d, [id]: { ...(d[id] || {}), ...patch } }));
  };

  const save = async (svcId) => {
    const value = (draft[svcId]?.value || "").trim();
    if (value.length < 8) {
      setSvc(svcId, { error: "That key looks too short." });
      return;
    }
    setSvc(svcId, { busy: true, error: "", ok: false });
    try {
      await apiClient.post("/user/byok", { service: svcId, key: value });
      setSvc(svcId, { busy: false, ok: true, value: "" });
      await load();
      setTimeout(() => setSvc(svcId, { ok: false }), 2400);
    } catch (e) {
      const msg = e?.response?.data?.detail?.message
        || e?.response?.data?.detail
        || "Could not save key.";
      setSvc(svcId, { busy: false, error: typeof msg === "string" ? msg : "Could not save key." });
    }
  };

  const removeKey = async (svcId) => {
    if (!window.confirm("Remove this saved key? Future renders will fall back to the platform key.")) return;
    setSvc(svcId, { busy: true, error: "" });
    try {
      await apiClient.delete(`/user/byok/${svcId}`);
      setSvc(svcId, { busy: false, value: "" });
      await load();
    } catch (e) {
      setSvc(svcId, { busy: false, error: "Could not remove key." });
    }
  };

  if (loading) {
    return (
      <main className="settings-keys-main">
        <div className="settings-keys-loading" data-testid="settings-keys-loading">Loading…</div>
      </main>
    );
  }

  if (!data?.byok_allowed) {
    return (
      <main className="settings-keys-main">
        <div className="settings-keys-shell">
          <Link to="/scripts" className="settings-keys-back" data-testid="settings-keys-back">
            <ArrowLeft size={14} /> Back
          </Link>
          <header className="settings-keys-hero">
            <KeyRound size={36} className="settings-keys-hero-icon" />
            <h1 className="settings-keys-title">API Keys</h1>
            <p className="settings-keys-sub">
              Bring-your-own-key is part of the <strong>Pro Plus</strong> tier. Upgrade to plug in your own OpenAI, HeyGen, and fal.ai keys — your renders will draw from your own quotas.
            </p>
          </header>
        </div>
      </main>
    );
  }

  return (
    <main className="settings-keys-main" data-testid="settings-keys-main">
      <div className="settings-keys-shell">
        <Link to="/scripts" className="settings-keys-back" data-testid="settings-keys-back">
          <ArrowLeft size={14} /> Back
        </Link>
        <header className="settings-keys-hero">
          <KeyRound size={36} className="settings-keys-hero-icon" />
          <h1 className="settings-keys-title">API Keys</h1>
          <p className="settings-keys-sub">
            Plug in your own keys to draw renders from your own provider quotas. Keys are encrypted at rest and never displayed once saved.
          </p>
          <div className="settings-keys-trust">
            <ShieldCheck size={14} />
            <span>Encrypted with Fernet · Hidden from the dashboard after save</span>
          </div>
        </header>

        <div className="settings-keys-list">
          {(data.services || []).map((svc) => {
            const d = draft[svc.id] || {};
            return (
              <section
                key={svc.id}
                className={`settings-key-card ${svc.configured ? "is-saved" : ""}`}
                data-testid={`settings-key-card-${svc.id}`}
              >
                <header className="settings-key-card-head">
                  <div>
                    <h2 className="settings-key-card-title">{svc.label}</h2>
                    <p className="settings-key-card-purpose">{svc.purpose}</p>
                  </div>
                  {svc.configured && (
                    <span className="settings-key-card-badge" data-testid={`settings-key-saved-${svc.id}`}>
                      <Check size={12} /> Saved · {svc.hint}
                    </span>
                  )}
                </header>

                <div className="settings-key-card-body">
                  <label className="settings-key-label" htmlFor={`settings-key-input-${svc.id}`}>
                    Your {svc.label} key
                  </label>
                  <div className="settings-key-row">
                    <input
                      id={`settings-key-input-${svc.id}`}
                      type="password"
                      autoComplete="off"
                      className="settings-key-input"
                      placeholder={svc.key_hint}
                      value={d.value || ""}
                      onChange={(e) => setSvc(svc.id, { value: e.target.value, error: "", ok: false })}
                      data-testid={`settings-key-input-${svc.id}`}
                    />
                    <button
                      type="button"
                      className="settings-key-save-btn"
                      onClick={() => save(svc.id)}
                      disabled={d.busy || !(d.value || "").trim()}
                      data-testid={`settings-key-save-${svc.id}`}
                    >
                      {d.busy ? "Saving…" : (svc.configured ? "Replace" : "Save key")}
                    </button>
                    {svc.configured && (
                      <button
                        type="button"
                        className="settings-key-delete-btn"
                        onClick={() => removeKey(svc.id)}
                        disabled={d.busy}
                        title="Remove saved key"
                        data-testid={`settings-key-delete-${svc.id}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                  {d.ok && (
                    <div className="settings-key-ok" data-testid={`settings-key-ok-${svc.id}`}>
                      <Check size={12} /> Key saved.
                    </div>
                  )}
                  {d.error && (
                    <div className="settings-key-err" data-testid={`settings-key-err-${svc.id}`}>
                      {d.error}
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>

        <footer className="settings-keys-foot">
          <p>
            Need help finding your keys? See{" "}
            <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">
              OpenAI <ExternalLink size={11} />
            </a>{", "}
            <a href="https://app.heygen.com/settings?nav=API" target="_blank" rel="noreferrer">
              HeyGen <ExternalLink size={11} />
            </a>{", "}
            <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noreferrer">
              fal.ai <ExternalLink size={11} />
            </a>.
          </p>
        </footer>
      </div>
    </main>
  );
}
