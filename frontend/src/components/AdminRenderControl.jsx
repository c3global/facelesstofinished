import React, { useEffect, useState } from "react";
import { ShieldAlert, X } from "lucide-react";
import { apiClient } from "../App";

/**
 * AdminRenderControl — admin-only override for the dry-run default.
 *
 * Rules (enforced both client-side and server-side):
 *   - This component is rendered ONLY when the current user is admin. The
 *     wrapper in Studio.jsx gates this on `currentUser.isAdmin`.
 *   - Default is OFF on every page mount — we deliberately do NOT persist
 *     to localStorage so every render starts in dry-run for safety. Admin
 *     has to actively tick the box each session.
 *   - Live cost estimate is fetched from `/studio/render/estimate` whenever
 *     the candidate render payload changes.
 *   - When the admin ticks "Use real render" and clicks the page CTA, the
 *     parent calls `confirmAdminRealRender()` which renders the confirm
 *     modal exported below.
 */
export default function AdminRenderControl({ payload, useReal, setUseReal }) {
  const [estimate, setEstimate] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!payload || !payload.script?.trim()) {
      setEstimate(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await apiClient.post("/studio/render/estimate", payload);
        if (!cancelled) {
          setEstimate(r.data);
          setErr("");
        }
      } catch (e) {
        if (!cancelled) setErr(e?.response?.data?.detail || "Could not estimate cost.");
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [JSON.stringify(payload)]); // eslint-disable-line react-hooks/exhaustive-deps

  const dollars = estimate ? estimate.estimated_cost_dollars.toFixed(2) : "—";
  const exceedsCap = estimate?.exceeds_cap;

  return (
    <div className="admin-render-control" data-testid="admin-render-control">
      <div className="admin-render-head">
        <ShieldAlert size={13} />
        <span>Admin · render controls</span>
      </div>
      <label className="admin-render-row" data-testid="admin-real-toggle-row">
        <input
          type="checkbox"
          data-testid="admin-real-toggle"
          checked={useReal}
          disabled={exceedsCap}
          onChange={(e) => setUseReal(e.target.checked)}
        />
        <span className="admin-render-label">
          Use real render ({estimate ? `~$${dollars}` : "calculating…"})
        </span>
      </label>
      {exceedsCap && (
        <p className="admin-render-warn" data-testid="admin-cap-warning">
          Estimated ${dollars} exceeds the ${(estimate.cap_dollars).toFixed(2)} hard cap. Backend will reject this render — shorten the script or pick a cheaper mode.
        </p>
      )}
      {err && <p className="admin-render-warn" data-testid="admin-estimate-error">{err}</p>}
      {!useReal && !exceedsCap && (
        <p className="admin-render-hint">
          Currently running in DRY-RUN — no real API spend. Tick the box above to fire a real render after a confirmation prompt.
        </p>
      )}
    </div>
  );
}

/**
 * Confirm-real-render modal. Renders 1-second-delayed confirm button to
 * prevent reflex double-clicks burning credits.
 */
export function ConfirmRealRenderModal({ estimateDollars, onConfirm, onCancel }) {
  const [armedIn, setArmedIn] = useState(1000); // ms remaining until confirm button enables

  useEffect(() => {
    if (armedIn <= 0) return;
    const t = setTimeout(() => setArmedIn((ms) => Math.max(0, ms - 100)), 100);
    return () => clearTimeout(t);
  }, [armedIn]);

  return (
    <div className="modal-backdrop" data-testid="confirm-real-render-modal">
      <div className="confirm-real-card" role="dialog" aria-modal="true">
        <header className="confirm-real-head">
          <h3>Fire a real render?</h3>
          <button
            type="button"
            className="icon-btn"
            data-testid="confirm-real-close"
            onClick={onCancel}
            aria-label="Cancel"
          >
            <X size={14} />
          </button>
        </header>
        <p className="confirm-real-body">
          This will spend approximately{" "}
          <strong data-testid="confirm-real-cost">${estimateDollars}</strong>{" "}
          in real HeyGen / fal.ai API credits.
        </p>
        <p className="confirm-real-body" style={{ opacity: 0.7 }}>
          Dry-run is recommended for testing. Only proceed if you intend to
          spend real credits on this render.
        </p>
        <div className="confirm-real-actions">
          <button
            type="button"
            className="header-btn"
            data-testid="confirm-real-cancel"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="cta-btn confirm-real-go"
            data-testid="confirm-real-go"
            disabled={armedIn > 0}
            onClick={onConfirm}
          >
            {armedIn > 0
              ? `Wait ${Math.ceil(armedIn / 100) / 10}s…`
              : `Render for $${estimateDollars}`}
          </button>
        </div>
      </div>
    </div>
  );
}
