import React from "react";
import { useNavigate, useLocation, NavLink } from "react-router-dom";
import { LogOut, Sun, Moon, FileText, Wand2, Shield, BookOpen } from "lucide-react";
import { useAuth, useTheme } from "../App";

export default function Header() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  const loc = useLocation();

  // Logo naming is inverse: the file named "light" has light-colored text and is
  // designed to sit on a DARK background; "dark" has dark-colored text for LIGHT bg.
  const logoSrc = theme === "dark" ? "/logo-light.png" : "/logo-dark.png";
  const showNav = user && loc.pathname !== "/login";

  return (
    <header className="site-header" data-testid="site-header">
      <div className="brand" data-testid="brand">
        <img
          src={logoSrc}
          alt="Faceless 48 — The 48-Hour Publishing System"
          className="brand-logo"
          data-testid="brand-logo"
        />
        {showNav && (
          <nav className="site-nav" data-testid="site-nav">
            <NavLink
              to="/scripts"
              className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
              data-testid="nav-scripts"
            >
              <FileText size={13} /> Script Engine
            </NavLink>
            {/*
              Studio nav is ALWAYS visible — even to users without the
              `studio` entitlement. Clicking it lands them on the existing
              paywall (`RequireStudio` → `<EntitlementPaywall>`) which is
              the conversion prompt. Hiding the link entirely (the pre-
              2026-02-23 behavior) meant Base-only users never even knew
              Studio existed → zero in-app conversion path. The small
              "Upgrade" pill makes it clear the feature is gated without
              feeling like a tease.
            */}
            <NavLink
              to="/studio"
              className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
              data-testid="nav-studio"
            >
              <Wand2 size={13} /> Studio
              {!user?.entitlements?.includes("studio") && (
                <span className="nav-upgrade-pill" data-testid="nav-studio-upgrade-pill">
                  Upgrade
                </span>
              )}
            </NavLink>
            {/* Resources — the 5-PDF Production Toolkit (Voiceover, B-Roll,
                Thumbnail Kit, Production Map, Publishing Checklist). Visible
                to every signed-in buyer regardless of tier because the
                guides themselves are static reference material that benefits
                everyone, and they were a promised deliverable on the
                pre-migration Netlify site. */}
            <NavLink
              to="/resources"
              className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
              data-testid="nav-resources"
            >
              <BookOpen size={13} /> Resources
            </NavLink>
            {user?.isAdmin && (
              <NavLink
                to="/admin"
                className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
                data-testid="nav-admin"
              >
                <Shield size={13} /> Admin
              </NavLink>
            )}
          </nav>
        )}
      </div>
      <div className="header-meta">
        {showNav && (
          <span className="header-email" data-testid="header-email">{user.email}</span>
        )}
        <button
          className="theme-toggle"
          data-testid="theme-toggle"
          onClick={toggle}
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={theme === "dark" ? "Light mode" : "Dark mode"}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        {showNav && (
          <button
            className="header-btn"
            data-testid="logout-btn"
            onClick={() => { logout(); nav("/login"); }}
          >
            <LogOut size={13} /> Sign out
          </button>
        )}
      </div>
    </header>
  );
}
