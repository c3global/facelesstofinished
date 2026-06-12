import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuth } from "../App";

export default function Header() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();

  // Hide on login page
  if (loc.pathname === "/login") return null;

  return (
    <header className="site-header" data-testid="site-header">
      <div className="brand" data-testid="brand">
        <span className="brand-mark">F</span>
        <span>Faceless to Finished — Studio</span>
      </div>
      <div className="header-meta">
        {user && <span className="header-email" data-testid="header-email">{user.email}</span>}
        {user && (
          <button
            className="header-btn"
            data-testid="logout-btn"
            onClick={() => { logout(); nav("/login"); }}
          >
            <LogOut size={13} style={{ marginRight: 6, verticalAlign: -2 }} /> Sign out
          </button>
        )}
      </div>
    </header>
  );
}
