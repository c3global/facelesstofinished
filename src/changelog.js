export const APP_VERSION = '1.8.0';

export const CHANGELOG = [
  {
    version: '1.8.0',
    date: '2026-06-15',
    changes: [
      'Sticky results nav bar with Jump-to-Script / Jump-to-Shorts anchors and Copy Script / Copy All Shorts buttons — always visible while you work',
      'Collapsible script sections — click any section header to collapse or expand; content is preserved (nothing is lost)',
      'Collapse all / Expand all toggle in the nav bar for long-form scripts',
      'Auto-scroll to newly generated shorts so you never have to hunt for them',
      'Copy All Shorts and per-variant Copy this Short buttons added to the shorts result',
      'Fix: invisible "selected" pill in light mode on the Cut into Shorts platform picker',
      'Fix: long-form script generation no longer times out on Medium/Long output',
      'Fix: updated to Sonnet 4.6 (the previous snapshot was retired by Anthropic)',
    ],
  },
  {
    version: '1.7.0',
    date: '2026-05-29',
    changes: [
      'Studio (Video Engine) UI shell — coming soon, gated tier',
      'Resource library: PDF assets',
      'Admin: bulk delete, optimistic UI, integrated session login',
      'Admin: engagement, revenue, and signups stats',
      'Backend: race-condition-safe entitlement grants',
      'Funnels: items[]-aware webhook for multi-product orders',
    ],
  },
  {
    version: '1.6.0',
    date: '2026-05-27',
    changes: ['Earlier release — details TBD'],
  },
];
