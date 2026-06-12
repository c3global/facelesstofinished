import React from "react";

// Visual phone-frame wrapper for Shorts output. Uses --platform-accent which is
// set on the document root by Scripts.jsx whenever the user picks a platform.
const PLATFORM_LABEL = {
  youtube: "YOUTUBE",
  reels: "REELS",
  tiktok: "TIKTOK",
};

export default function PhoneFrame({ platform = "youtube", children }) {
  return (
    <div className="phone-wrap" data-testid="phone-wrap" data-platform={platform}>
      <div className="phone-shell">
        <div className="phone-notch" aria-hidden="true" />
        {/* Status bar */}
        <div className="phone-status">
          <span className="phone-time">9:41</span>
          <span className="phone-platform-badge" data-testid="phone-platform-badge">
            {PLATFORM_LABEL[platform] || "VIDEO"}
          </span>
        </div>
        {/* Screen content */}
        <div className="phone-screen" data-testid="phone-screen">{children}</div>
      </div>
    </div>
  );
}
