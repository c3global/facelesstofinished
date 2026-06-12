import React, { useEffect, useState } from 'react';

const STORAGE_KEY = 'f48_theme';
const OPTIONS = [
  { value: 'light', label: 'Light', icon: '☀' },
  { value: 'dark', label: 'Dark', icon: '☾' },
  { value: 'system', label: 'System', icon: '◐' },
];

function resolveTheme(choice) {
  if (choice === 'light' || choice === 'dark') return choice;
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

function applyTheme(choice) {
  const resolved = resolveTheme(choice);
  document.documentElement.setAttribute('data-theme', resolved);
}

export function initTheme() {
  if (typeof window === 'undefined') return;
  const stored = localStorage.getItem(STORAGE_KEY) || 'system';
  applyTheme(stored);
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    mq.addEventListener?.('change', () => {
      const current = localStorage.getItem(STORAGE_KEY) || 'system';
      if (current === 'system') applyTheme('system');
    });
  }
}

export default function ThemeToggle() {
  const [choice, setChoice] = useState(() => {
    if (typeof window === 'undefined') return 'system';
    return localStorage.getItem(STORAGE_KEY) || 'system';
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, choice);
    applyTheme(choice);
  }, [choice]);

  return (
    <div className="theme-toggle" role="radiogroup" aria-label="Color theme">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={choice === opt.value}
          className={`theme-option ${choice === opt.value ? 'is-selected' : ''}`}
          onClick={() => setChoice(opt.value)}
          title={opt.label}
        >
          <span aria-hidden="true">{opt.icon}</span>
          <span className="sr-only">{opt.label}</span>
        </button>
      ))}
    </div>
  );
}
