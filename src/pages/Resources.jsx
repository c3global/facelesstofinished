import React from 'react';
import { Link } from 'react-router-dom';

const RESOURCES = [
  {
    key: 'voiceover',
    number: '01',
    title: 'Pitch Perfect AI Voiceover Guide',
    description: 'Voice selection, pacing, and delivery techniques for natural-sounding AI narration.',
    file: '/resources/01_Voiceover_Guide.html',
    accent: '#7F77DD',
  },
  {
    key: 'broll',
    number: '02',
    title: 'B-Roll Prompt Bank',
    description: 'Ready-to-use AI image and video prompts for every shot type in your script.',
    file: '/resources/02_BRoll_Prompt_Bank.html',
    accent: '#378ADD',
  },
  {
    key: 'thumbnail',
    number: '03',
    title: 'Thumbnail Kit',
    description: 'Click-worthy thumbnail templates, color theory, and composition formulas.',
    file: '/resources/03_Thumbnail_Kit.html',
    accent: '#C41A18',
  },
  {
    key: 'production',
    number: '04',
    title: 'Production Map',
    description: 'The 48-hour workflow from idea to upload, with timing for every step.',
    file: '/resources/04_Production_Map.html',
    accent: '#1D9E75',
  },
  {
    key: 'publishing',
    number: '05',
    title: 'Publishing Checklist',
    description: 'Titles, tags, descriptions, end screens — everything you need before you hit publish.',
    file: '/resources/05_Publishing_Checklist.html',
    accent: '#C9956C',
  },
];

export default function Resources() {
  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/faceless" aria-label="Faceless 48 — The 48-Hour Publishing System">
          <img src="/faceless48-lockup.png" alt="Faceless 48 — The 48-Hour Publishing System" />
        </a>
        <div className="title-block">
          <h1 className="title">Resource Library</h1>
        </div>
        <div className="header-spacer" aria-hidden="true" />
      </header>

      <main className="main">
        <section className="hero">
          <div>
            <p className="eyebrow">Faceless to Finished · Production Toolkit</p>
            <h2 className="hero-headline">Everything you need<br/>to finish in 48 hours.</h2>
            <p className="hero-sub">
              Five guides covering voiceover, B-roll, thumbnails, workflow, and publishing. Open any guide in a new tab.
            </p>
          </div>

          <div className="nav-row">
            <Link to="/faceless" className="ghost-btn">← Back to Script Engine</Link>
          </div>
        </section>

        <section className="resources-grid">
          {RESOURCES.map((r) => (
            <a
              key={r.key}
              className="resource-card"
              href={r.file}
              target="_blank"
              rel="noopener noreferrer"
              style={{ borderLeftColor: r.accent, '--card-accent': r.accent }}
            >
              <div className="resource-number" style={{ color: r.accent }}>{r.number}</div>
              <h3 className="resource-title">{r.title}</h3>
              <p className="resource-desc">{r.description}</p>
              <span className="resource-open" style={{ color: r.accent }}>Open guide →</span>
            </a>
          ))}
        </section>
      </main>

      <footer className="site-footer">
        <img className="footer-mark" src="/faceless48-mark.png" alt="Faceless 48" />
        <div className="footer-text">
          <div className="footer-brand">C3 Global</div>
          <div>© 2026 · sprint.c3global.co/faceless</div>
        </div>
      </footer>
    </div>
  );
}
