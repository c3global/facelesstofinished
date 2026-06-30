// Public roadmap for F2F48. Mirrors the changelog pattern: edit this file
// when a column changes; the /roadmap page re-renders automatically.
//
// Buckets (intentional order, top → bottom):
//   shipped     — Already in customers' hands. Builds AppSumo credibility.
//   inProgress  — Actively being built right now.
//   planned     — Committed next. No dates (dates slip; commitment doesn't).
//   considering — On our radar. Buyer demand will move these up.
//
// Each item: { title, blurb, tag? }. `tag` adds a small chip next to the
// title (e.g. "P0", "AppSumo", "Top request"). Keep blurbs to one sentence.
//
// Voice rule: founder-honest, customer-facing. No internal jargon
// (no "fal.ai", "HeyGen v3", "GridFS", "JWT") — describe the *benefit*.

export const ROADMAP = {
  shipped: {
    label: "Shipped",
    note: "Already live and working for every buyer.",
    items: [
      {
        title: "Script Engine",
        blurb: "Long-form, Shorts, and Sprint modes. Generate 3 platform-tuned scripts at once with side-by-side compare view.",
      },
      {
        title: "Studio — Avatar mode",
        blurb: "Talking-head videos in 16:9 or 9:16 with burned-in captions. Browse 1,200+ avatars and 2,300+ voices.",
      },
      {
        title: "Studio — Faceless mode",
        blurb: "Slideshow-style videos with AI voiceover, AI-generated visuals, and stock B-roll. Optional caption burn-in.",
      },
      {
        title: "Thumbnail Engine",
        blurb: "Two engines (Premium + Fast), three aspect ratios, prompt rewriter, full-screen preview, batch-generate from any script.",
      },
      {
        title: "Bring Your Own Keys (BYOK)",
        blurb: "Pro Plus + Founders can plug in their own Anthropic, OpenAI, Google, ElevenLabs, HeyGen, and fal.ai keys. Encrypted at rest.",
        tag: "Pro Plus",
      },
      {
        title: "Admin Dashboard",
        blurb: "Usage leaderboard, buyer drilldown, activity feed, license management, CSV exports. For Charity + your team only.",
      },
      {
        title: "Light + Dark themes",
        blurb: "Switch in the header. Every page, every card, every chip — polished to readable contrast in both modes.",
      },
      {
        title: "AppSumo redemption flow",
        blurb: "Paste your code, instantly unlock your tier. Works from the footer, the login screen, or your profile dropdown.",
        tag: "AppSumo",
      },
    ],
  },

  inProgress: {
    label: "In Progress",
    note: "Actively being built right now.",
    items: [
      {
        title: "Production deploy + AppSumo launch",
        blurb: "Final pre-launch hardening — Fernet-encrypted BYOK vault, deploy health checks, last QA pass on captioned Faceless renders.",
        tag: "This week",
      },
      {
        title: "GoHighLevel CRM sync",
        blurb: "Auto-push every new buyer + redemption to your GHL pipeline so onboarding sequences fire the moment someone joins.",
      },
    ],
  },

  planned: {
    label: "Planned",
    note: "Committed next. We don't promise dates — we promise these will ship.",
    items: [
      {
        title: "Canva integration",
        blurb: "One-click export your thumbnails into a new Canva design so you can layer your branded text, logo, and overlays without leaving the workflow.",
        tag: "Top request",
      },
      {
        title: "Cinematic Faceless (true text-to-video)",
        blurb: "Upgrade Faceless mode from static-image slideshows to real motion video. Targeting Veo, Pika, or Kling — whichever ships the best 9:16 quality.",
        tag: "P0",
      },
      {
        title: "Upload your own B-roll",
        blurb: "Drop in your own video clips per scene instead of relying on stock. Mix-and-match with AI-generated visuals.",
      },
      {
        title: "Record your own voiceover",
        blurb: "Browser mic recorder built into the Voice picker. Skip the AI voice entirely when you want your real voice.",
      },
      {
        title: "Brand kits",
        blurb: "Save your colors, fonts, and logo once — they auto-apply to every thumbnail and on-screen text caption.",
      },
      {
        title: "Bulk script-to-video (CSV upload)",
        blurb: "Paste in 50 topics, walk away, come back to 50 rendered videos. Built for content factories.",
      },
      {
        title: "AI music selection",
        blurb: "Smart background music picker that matches the mood, pace, and platform of each script — no more royalty-free hunting.",
      },
      {
        title: "Native publishing",
        blurb: "Render → publish straight to YouTube, TikTok, Instagram Reels, and YouTube Shorts. Schedule or post immediately.",
      },
      {
        title: "Performance analytics",
        blurb: "After you publish, pull views, watch-time, and engagement back into the dashboard. See which scripts and thumbnails actually convert.",
      },
    ],
  },

  considering: {
    label: "Considering",
    note: "On our radar. Tell us which one matters most — the loudest demand moves up to Planned.",
    items: [
      {
        title: "Voice cloning",
        blurb: "Clone your own voice via ElevenLabs so every Faceless render sounds like you, not a generic AI narrator.",
      },
      {
        title: "Team seats",
        blurb: "Multi-user workspaces — invite editors, give roles, share script + render libraries.",
      },
      {
        title: "Webhook + Zapier outbound",
        blurb: "Fire a webhook every time a render completes so your downstream tools (Notion, Airtable, Slack, etc.) get notified.",
      },
      {
        title: "Avatar background removal",
        blurb: "Drop in your own background behind any HeyGen avatar — your brand setting, b-roll, motion graphics, anything.",
      },
      {
        title: "Mobile app",
        blurb: "Native iOS + Android apps for reviewing renders, copying scripts, and approving thumbnails on the go.",
      },
    ],
  },
};
