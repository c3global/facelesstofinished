import React, { useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { fetchSession } from '../api.js';
import ThemeToggle from '../ThemeToggle.jsx';
import Footer from '../Footer.jsx';

const RESOURCES = [
  {
    key: 'voiceover',
    number: '01',
    title: 'Pitch Perfect AI Voiceover Guide',
    description: 'Voice selection, pacing, and delivery techniques for natural-sounding AI narration.',
    file: 'https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a2753050de795fc131142a0.pdf',
    accent: '#7F77DD',
  },
  {
    key: 'broll',
    number: '02',
    title: 'B-Roll Prompt Bank',
    description: 'Ready-to-use AI image and video prompts for every shot type in your script.',
    file: 'https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a275305f607d4002bd7d862.pdf',
    accent: '#378ADD',
  },
  {
    key: 'thumbnail',
    number: '03',
    title: 'Thumbnail Kit',
    description: 'Click-worthy thumbnail templates, color theory, and composition formulas.',
    file: 'https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a275305d91f654725b62870.pdf',
    accent: '#C41A18',
  },
  {
    key: 'production',
    number: '04',
    title: 'Production Map',
    description: 'The 48-hour workflow from idea to upload, with timing for every step.',
    file: 'https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a2753050de795fc131142a1.pdf',
    accent: '#1D9E75',
  },
  {
    key: 'publishing',
    number: '05',
    title: 'Publishing Checklist',
    description: 'Titles, tags, descriptions, end screens — everything you need before you hit publish.',
    file: 'https://assets.cdn.filesafe.space/RVXeSVbF3U7E56SwQumk/media/6a27530549e55f8519bafdf2.pdf',
    accent: '#C9956C',
  },
];

export default function Resources() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetchSession().then(setSession).finally(() => setLoading(false));
  }, []);
  if (loading) return <div className="page"><div className="loading-shell">Loading…</div></div>;
  if (!session) return <Navigate to="/" replace />;

  return (
    <div className="page">
      <header className="site-header">
        <a className="header-logo" href="/" aria-label="Faceless 48 — The 48-Hour Publishing System">
          <img src="/faceless48-lockup.png" alt="Faceless 48 — The 48-Hour Publishing System" />
        </a>
        <div className="title-block">
          <h1 className="title">Resource Library</h1>
        </div>
        <nav className="header-nav">
          <ThemeToggle />
        </nav>
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

      <Footer />
    </div>
  );
}
