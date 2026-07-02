import React, { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { Users, FileText, Film, ImageIcon, DollarSign, RefreshCw } from "lucide-react";
import { apiClient } from "../../App";

function fmtCents(c) {
  if (!c) return "$0";
  return `$${(c / 100).toFixed(2)}`;
}

function MetricTile({ icon: Icon, label, value, testid }) {
  return (
    <div className="stat-tile" data-testid={testid}>
      <div className="stat-tile-icon"><Icon size={18} /></div>
      <div>
        <div className="stat-tile-value">{value}</div>
        <div className="stat-tile-label">{label}</div>
      </div>
    </div>
  );
}

export default function StatsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await apiClient.get("/admin/stats");
      setData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to load stats");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) return <div className="admin-empty" data-testid="stats-loading">Loading stats…</div>;
  if (err) return <div className="admin-empty is-err" data-testid="stats-error">{err}</div>;
  if (!data) return null;

  return (
    <div className="admin-section" data-testid="stats-tab">
      <div className="admin-toolbar">
        <button className="admin-btn" onClick={load} data-testid="stats-refresh">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      <div className="stat-tiles">
        <MetricTile icon={Users} label="Total buyers" value={data.total_users} testid="stat-total-users" />
        <MetricTile icon={Users} label="Active (30d)" value={data.active_30d} testid="stat-active-30d" />
        <MetricTile icon={Film} label="Studio renders" value={data.total_renders} testid="stat-renders" />
        <MetricTile icon={FileText} label="Scripts generated" value={data.total_scripts} testid="stat-scripts" />
        <MetricTile icon={ImageIcon} label="Thumbnails generated" value={data.total_thumbnails ?? 0} testid="stat-thumbnails" />
        <MetricTile icon={DollarSign} label="Revenue (all-time)" value={fmtCents(data.revenue_cents)} testid="stat-revenue" />
      </div>

      <div className="stat-chart-wrap" data-testid="stats-chart-wrap">
        <div className="stat-chart-header">
          <h3 className="stat-chart-title">Signups over time</h3>
          <span className="admin-meta">{data.signups_series?.length || 0} days</span>
        </div>
        <div className="stat-chart">
          {data.signups_series?.length ? (
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data.signups_series} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="signupsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7F77DD" stopOpacity={0.6} />
                    <stop offset="100%" stopColor="#7F77DD" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(120,110,170,0.15)" />
                <XAxis dataKey="date" stroke="rgba(216,210,234,0.6)" fontSize={11} />
                <YAxis stroke="rgba(216,210,234,0.6)" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "#0F0A1E",
                    border: "1px solid rgba(127,119,221,0.4)",
                    borderRadius: 8,
                    color: "#E8E1F8",
                  }}
                  labelStyle={{ color: "#C9956C" }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#7F77DD"
                  strokeWidth={2}
                  fill="url(#signupsGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="admin-empty">No signups recorded yet.</div>
          )}
        </div>
      </div>

      <div className="stat-chart-wrap" data-testid="stats-ent-breakdown">
        <h3 className="stat-chart-title">Entitlement breakdown</h3>
        <div className="ent-breakdown-row">
          {Object.entries(data.entitlement_breakdown || {}).map(([ent, count]) => (
            <div key={ent} className="ent-breakdown-cell" data-testid={`ent-breakdown-${ent}`}>
              <span className={`ent-chip ent-chip-${ent}`}>{ent}</span>
              <strong className="ent-breakdown-count">{count}</strong>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
