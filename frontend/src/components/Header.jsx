import React from "react";
import { useNavigate, useLocation, NavLink } from "react-router-dom";
import { LogOut, Sun, Moon, FileText, Wand2, Shield } from "lucide-react";
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
            {user?.entitlements?.includes("studio") && (
              <NavLink
                to="/studio"
                className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
                data-testid="nav-studio"
              >
                <Wand2 size={13} /> Studio
              </NavLink>
            )}
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
