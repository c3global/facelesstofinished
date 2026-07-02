import React, { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../App";
import { Users, Activity as ActivityIcon, BarChart3, TrendingUp, KeyRound } from "lucide-react";
import BuyersTab from "../components/admin/BuyersTab";
import ActivityTab from "../components/admin/ActivityTab";
import StatsTab from "../components/admin/StatsTab";
import UsageTab from "../components/admin/UsageTab";
import LicensesTab from "../components/admin/LicensesTab";

const TABS = [
  { key: "buyers", label: "Buyers", Icon: Users },
  { key: "usage", label: "Usage", Icon: TrendingUp },
  { key: "licenses", label: "Licenses", Icon: KeyRound },
  { key: "activity", label: "Activity", Icon: ActivityIcon },
  { key: "stats", label: "Stats", Icon: BarChart3 },
];

export default function Admin() {
  const { user, loading } = useAuth();
  const [tab, setTab] = useState(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem("f48_admin_tab") : null;
    return TABS.find((t) => t.key === stored) ? stored : "buyers";
  });

  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem("f48_admin_tab", tab);
  }, [tab]);

  if (loading) return <div className="page-loading" data-testid="page-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.isAdmin) {
    return (
      <div className="page-locked" data-testid="admin-locked">
        Admin access required.
      </div>
    );
  }

  return (
    <div className="admin-page" data-testid="admin-page">
      <div className="admin-page-header">
        <div>
          <div className="admin-eyebrow" data-testid="admin-eyebrow">ADMIN PANEL</div>
          <h1 className="admin-title" data-testid="admin-title">Operations dashboard</h1>
          <p className="admin-subtitle">Buyers, activity, signups — all from the live emergent backend.</p>
        </div>
      </div>
      <div className="admin-tabs" role="tablist" data-testid="admin-tabs">
        {TABS.map(({ key, label, Icon }) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            data-testid={`admin-tab-${key}`}
            className={`admin-tab ${tab === key ? "is-active" : ""}`}
            onClick={() => setTab(key)}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      <div className="admin-tab-body">
        {tab === "buyers" && <BuyersTab />}
        {tab === "usage" && <UsageTab />}
        {tab === "licenses" && <LicensesTab />}
        {tab === "activity" && <ActivityTab />}
        {tab === "stats" && <StatsTab />}
      </div>
    </div>
  );
}
