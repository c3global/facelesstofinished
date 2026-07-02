import React from "react";
import { useLocation, NavLink, Link } from "react-router-dom";
import { Sun, Moon, FileText, Wand2, Shield, BookOpen, Image as ImageIcon } from "lucide-react";
import { useAuth, useTheme } from "../App";
import ProfileMenu from "./ProfileMenu";

export default function Header() {
  const { user } = useAuth();
  const { theme, toggle } = useTheme();
  const loc = useLocation();

  // Logo naming is inverse: the file named "light" has light-colored text and is
  // designed to sit on a DARK background; "dark" has dark-colored text for LIGHT bg.
  const logoSrc = theme === "dark" ? "/logo-light.png" : "/logo-dark.png";
  const showNav = user && loc.pathname !== "/login";
  // Public visitors (no user yet) get a 3-link public nav on the right side
  // of the header — Roadmap · Changelog · Sign in. Shown on EVERY route
  // where the user isn't signed in (including /login itself, so the
  // Roadmap + Changelog links are always discoverable from the same spot).
  const showPublicNav = !user;

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
              to="/thumbnails"
              className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
              data-testid="nav-thumbnails"
            >
              <ImageIcon size={13} /> Thumbnails
            </NavLink>
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
        {showPublicNav && (
          <nav className="site-public-nav" data-testid="site-public-nav" aria-label="Public navigation">
            <Link to="/roadmap" className="public-nav-link" data-testid="public-nav-roadmap">
              Roadmap
            </Link>
            <Link to="/changelog" className="public-nav-link" data-testid="public-nav-changelog">
              Changelog
            </Link>
            {loc.pathname !== "/login" && (
              <Link to="/login" className="public-nav-cta" data-testid="public-nav-signin">
                Sign in
              </Link>
            )}
          </nav>
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
        {showNav && <ProfileMenu />}
      </div>
    </header>
  );
}
