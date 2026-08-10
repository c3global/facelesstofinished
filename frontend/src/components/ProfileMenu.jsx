import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronDown, Crown, KeyRound, ShieldCheck, ArrowUpCircle, LogOut } from "lucide-react";
import { apiClient, useAuth } from "../App";

/**
 * Profile dropdown shown in the right side of the Header. Replaces the
 * pre-Group-D flat "email + sign-out" pair. Adds:
 *
 *   • Tier label ("Starter" / "Pro" / "Pro Plus" / "Founder")
 *   • Optional Founder badge (small copper Crown chip for the legacy 39)
 *   • "Upgrade plan" link — only renders when /api/me/upgrade-target says
 *     it should be visible (auto-flips between AppSumo stack URL during
 *     the campaign and the operator's own pricing URL after, per Group D)
 *   • "Redeem code" link → /redeem (always visible; doesn't reveal AppSumo)
 *   • Sign out
 */
export default function ProfileMenu() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [quota, setQuota] = useState(null);
  const [upgrade, setUpgrade] = useState(null);
  const wrapRef = useRef(null);

  const loadMeta = useCallback(async () => {
    try {
      const [q, u] = await Promise.all([
        apiClient.get("/me/quota"),
        apiClient.get("/me/upgrade-target"),
      ]);
      setQuota(q.data || null);
      setUpgrade(u.data || null);
      // Stamp body[data-founder] so the rest of the app can apply the
      // copper theme accent via CSS attribute selectors. Single source of
      // truth — ProfileMenu is the only component that needs to do this
      // because it's mounted whenever any signed-in user is browsing.
      const isFounder = q.data?.tier_id === "founder" || q.data?.tier_label === "Founder";
      try {
        if (isFounder) document.body.dataset.founder = "true";
        else delete document.body.dataset.founder;
      } catch {}
    } catch {
      // Non-fatal — menu still renders with just email + sign-out.
    }
  }, []);

  // Cleanup body[data-founder] when ProfileMenu unmounts (sign-out). Avoids
  // a brief copper-themed login page flash on a public computer.
  useEffect(() => {
    return () => {
      try { delete document.body.dataset.founder; } catch {}
    };
  }, []);

  useEffect(() => { if (user) loadMeta(); }, [user, loadMeta]);

  // Click-outside dismiss. Bind only while the menu is open to keep listener
  // overhead at zero the rest of the time.
  useEffect(() => {
    if (!open) return undefined;
    const onClick = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (!user) return null;

  // The Founder bucket is purely the `founders: true` flag — NEVER a
  // publicly-redeemable tier. Post-v1.20.5 pivot the label is also "Founder"
  // in quota.tier_label but we double-check via tier_id to avoid any drift.
  const isFounder = quota?.tier_id === "founder" || quota?.tier_label === "Founder";
  const tierLabel = quota?.tier_label || (quota?.unlimited ? "Owner" : null);

  return (
    <div className="profile-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`profile-menu-trigger ${isFounder ? "is-founder" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="profile-menu-trigger"
      >
        {isFounder && (
          <span className="profile-founder-badge" data-testid="profile-founder-badge">
            <Crown size={11} /> Founder
          </span>
        )}
        <span className="profile-menu-email">{user.email}</span>
        <ChevronDown size={13} className={`profile-menu-caret ${open ? "is-open" : ""}`} />
      </button>

      {open && (
        <div className="profile-menu" role="menu" data-testid="profile-menu">
          <div className="profile-menu-head">
            <div className="profile-menu-email-full">{user.email}</div>
            {tierLabel && (
              <div className={`profile-menu-tier ${isFounder ? "is-founder" : ""}`}>
                {isFounder && <Crown size={11} />}
                {tierLabel}
              </div>
            )}
          </div>

          {upgrade?.visible && upgrade.url && (
            <a
              href={upgrade.url}
              target="_blank"
              rel="noopener noreferrer"
              className="profile-menu-item profile-menu-item-upgrade"
              role="menuitem"
              data-testid="profile-menu-upgrade"
              onClick={() => setOpen(false)}
            >
              <ArrowUpCircle size={14} />
              <span>{upgrade.label || "Upgrade plan"}</span>
            </a>
          )}

          <Link
            to="/redeem"
            className="profile-menu-item"
            role="menuitem"
            data-testid="profile-menu-redeem"
            onClick={() => setOpen(false)}
          >
            <KeyRound size={14} />
            <span>Redeem code</span>
          </Link>

          {quota?.byok_allowed && (
            <Link
              to="/settings/keys"
              className="profile-menu-item"
              role="menuitem"
              data-testid="profile-menu-keys"
              onClick={() => setOpen(false)}
            >
              <ShieldCheck size={14} />
              <span>API keys</span>
            </Link>
          )}

          <button
            type="button"
            className="profile-menu-item profile-menu-item-signout"
            role="menuitem"
            data-testid="profile-menu-signout"
            onClick={() => { setOpen(false); logout(); nav("/login"); }}
          >
            <LogOut size={14} />
            <span>Sign out</span>
          </button>
        </div>
      )}
    </div>
  );
}
