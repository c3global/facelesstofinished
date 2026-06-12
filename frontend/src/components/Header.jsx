import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { LogOut, Sun, Moon } from "lucide-react";
import { useAuth, useTheme } from "../App";

export default function Header() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  const loc = useLocation();

  return (
    <header className="site-header" data-testid="site-header">
      <div className="brand" data-testid="brand">
        <span className="brand-mark">F</span>
        <span>
          <span className="brand-name">Faceless to Finished</span>{" "}
          <span className="brand-sub">— Studio</span>
        </span>
      </div>
      <div className="header-meta">
        {user && loc.pathname !== "/login" && (
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
        {user && loc.pathname !== "/login" && (
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
