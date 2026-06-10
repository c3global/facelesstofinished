import React from 'react';
import { APP_VERSION, CHANGELOG } from './changelog.js';

export default function Footer() {
  return (
    <footer className="site-footer">
      <img className="footer-mark" src="/faceless48-mark.png" alt="Faceless 48" />
      <div className="footer-text">
        <div className="footer-line">
          <span>© 2026 C3 Global</span>
          <details className="footer-changelog">
            <summary className="footer-version">v{APP_VERSION}</summary>
            <div className="footer-changelog-panel">
              <h4>Changelog</h4>
              {CHANGELOG.map((entry) => (
                <div key={entry.version} className="footer-changelog-entry">
                  <div className="footer-changelog-head">
                    <strong>v{entry.version}</strong>
                    <span className="footer-changelog-date">{entry.date}</span>
                  </div>
                  <ul>
                    {entry.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </details>
        </div>
      </div>
    </footer>
  );
}
