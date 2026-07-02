import React, { useCallback, useEffect, useRef, useState } from "react";
import { Zap, Crown, X, ArrowUpCircle } from "lucide-react";
import { apiClient } from "../App";

/**
 * Renders the "12 of 15 renders · resets Mar 1" pill in the Studio header.
 * Founders + dev/grant emails get a "Founder" or "Owner" badge with no
 * usage bar. Click the pill to open an inline tooltip with the full
 * breakdown (avatar sub-cap, exact reset date, upgrade hint when near cap).
 *
 * Refresh:
 *   - On mount
 *   - When the parent fires `bump` (incremented after each successful render
 *     dispatch) so the pill updates without a manual reload
 *   - Every 60s in the background as a soft sync
 */
function fmtResetDate(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return null;
  }
}

function daysUntil(iso) {
  if (!iso) return null;
  try {
    const ms = new Date(iso).getTime() - Date.now();
    if (!Number.isFinite(ms)) return null;
    return Math.max(0, Math.ceil(ms / 86_400_000));
  } catch {
    return null;
  }
}

export default function StudioQuotaPill({ bump = 0 }) {
  const [quota, setQuota] = useState(null);
  const [upgrade, setUpgrade] = useState(null);
  const [open, setOpen] = useState(false);
  const popoverRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [q, u] = await Promise.all([
        apiClient.get("/me/quota"),
        apiClient.get("/me/upgrade-target"),
      ]);
      setQuota(q.data);
      setUpgrade(u.data);
    } catch {
      // Quota endpoint failing shouldn't break the page — just hide the pill.
      setQuota(null);
      setUpgrade(null);
    }
  }, []);

  useEffect(() => { load(); }, [load, bump]);
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  // Click-outside closes the popover. Bind only while open to keep listener
  // overhead at zero for the 99% of the time the user isn't inspecting it.
  useEffect(() => {
    if (!open) return undefined;
    const onClick = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (!quota) return null;

  if (quota.unlimited) {
    return (
      <div className="quota-pill quota-pill-unlimited" data-testid="studio-quota-pill">
        <Crown size={13} />
        <span>{quota.tier_label || "Unlimited"} · unlimited renders</span>
      </div>
    );
  }

  const used = quota.renders_used ?? 0;
  const total = quota.renders_total ?? 0;
  const remaining = quota.renders_remaining ?? Math.max(0, total - used);
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const isLow = total > 0 && remaining <= Math.max(1, Math.ceil(total * 0.2));
  const isExhausted = total > 0 && remaining === 0;

  const resetLabel = fmtResetDate(quota.cycle_resets_at);
  const days = daysUntil(quota.cycle_resets_at);

  return (
    <div className="quota-pill-wrap" ref={popoverRef}>
      <button
        type="button"
        className={`quota-pill ${isExhausted ? "is-exhausted" : isLow ? "is-low" : ""}`}
        onClick={() => setOpen((v) => !v)}
        data-testid="studio-quota-pill"
        aria-expanded={open}
        title="Click for details"
      >
        <Zap size={13} />
        <span className="quota-pill-text">
          {used} of {total} renders
        </span>
        {resetLabel && (
          <span className="quota-pill-reset">· resets {resetLabel}</span>
        )}
      </button>

      {open && (
        <div className="quota-pop" data-testid="studio-quota-pop" role="dialog">
          <div className="quota-pop-head">
            <strong>{quota.tier_label}</strong>
            <button
              type="button"
              className="quota-pop-close"
              onClick={() => setOpen(false)}
              aria-label="Close"
              data-testid="studio-quota-close"
            >
              <X size={12} />
            </button>
          </div>

          <div className="quota-pop-row">
            <span>Renders</span>
            <span><b>{used}</b> of {total}</span>
          </div>
          <div className="quota-pop-bar" aria-hidden="true">
            <div className="quota-pop-bar-fill" style={{ width: `${pct}%` }} />
          </div>

          {quota.avatar_cap > 0 && (
            <>
              <div className="quota-pop-row" style={{ marginTop: 10 }}>
                <span>Avatar renders</span>
                <span><b>{quota.avatar_used ?? 0}</b> of {quota.avatar_cap}</span>
              </div>
              <div className="quota-pop-bar" aria-hidden="true">
                <div
                  className="quota-pop-bar-fill is-avatar"
                  style={{
                    width: `${Math.min(100, Math.round(((quota.avatar_used ?? 0) / quota.avatar_cap) * 100))}%`,
                  }}
                />
              </div>
            </>
          )}

          <div className="quota-pop-foot">
            {resetLabel ? (
              <span>
                Resets <b>{resetLabel}</b>
                {typeof days === "number" && days >= 0 && (
                  <> · in {days} day{days === 1 ? "" : "s"}</>
                )}
              </span>
            ) : (
              <span>Resets every 30 days from your purchase date.</span>
            )}
          </div>

          {isExhausted && (
            <div className="quota-pop-cta" data-testid="studio-quota-exhausted-cta">
              You've used every render this cycle.
              {resetLabel && <> Renders unlock again on <b>{resetLabel}</b>.</>}
            </div>
          )}

          {/* Upgrade CTA — only renders when (a) quota is low/exhausted AND
              (b) the backend's /me/upgrade-target says it's visible (which
              accounts for tier ceiling, founder status, and the auto-flip
              between AppSumo stack URL and your own pricing URL based on
              the campaign window). Hidden completely otherwise so it
              doesn't pester users who have plenty of headroom. */}
          {(isLow || isExhausted) && upgrade?.visible && upgrade.url && (
            <a
              href={upgrade.url}
              target="_blank"
              rel="noopener noreferrer"
              className="quota-pop-upgrade-btn"
              data-testid="studio-quota-upgrade-btn"
              onClick={() => setOpen(false)}
            >
              <ArrowUpCircle size={13} />
              <span>{upgrade.label || "Upgrade your plan"}</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
}
