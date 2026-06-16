import React from 'react';
import PhoneFrame from './PhoneFrame.jsx';
import { parseSections } from '../parser.js';

// Renders a horizontal swipeable stack of mini phone-mockup previews for batched
// shorts generations (Sprint, Multi-platform pack, Repurposer). Each item streams
// independently; tapping a mini expands it into a full-size phone with all sections.
export default function ResultGrid({ items, onExpand, expandedIdx }) {
  if (!items?.length) return null;
  return (
    <div className="result-grid">
      <div className="result-grid-strip">
        {items.map((item, i) => (
          <MiniResult
            key={item.id}
            item={item}
            isExpanded={expandedIdx === i}
            onClick={() => onExpand(i)}
          />
        ))}
      </div>
      {expandedIdx != null && items[expandedIdx] && (
        <ExpandedResult item={items[expandedIdx]} />
      )}
    </div>
  );
}

function MiniResult({ item, isExpanded, onClick }) {
  const { label, accent, platform, raw, status } = item;
  const sections = parseSections(raw);
  const script = sections.shortScript?.body || '';

  return (
    <button
      type="button"
      onClick={onClick}
      className={`result-mini ${isExpanded ? 'is-expanded' : ''}`}
      style={{ '--mini-accent': accent }}
      aria-label={`Open ${label}`}
    >
      <div className="result-mini-header">
        <span className="result-mini-chip">{label}</span>
        <span className={`result-mini-status status-${status}`}>
          {status === 'streaming' ? '●' : status === 'done' ? '✓' : status === 'error' ? '!' : '…'}
        </span>
      </div>
      <div className="result-mini-phone">
        <PhoneFrame scriptBody={script} platform={platform} />
      </div>
    </button>
  );
}

function ExpandedResult({ item }) {
  const { raw, platform, label, status } = item;
  const sections = parseSections(raw);
  return (
    <div className="result-expanded">
      <div className="result-expanded-header">
        <span className="result-mini-chip">{label}</span>
        {status === 'done' && raw && (
          <CopyOnly text={raw} label="Copy this Short" className="result-expanded-copy" />
        )}
      </div>
      <ShortsWorkflow sections={sections} platform={platform} />
    </div>
  );
}

// Shared 3-column workflow layout. Exported so the main Engine can use it too.
export function ShortsWorkflow({ sections, platform }) {
  const cards = {
    hooks: sections.hooks,
    titleVariants: sections.titleVariants,
    coverPrompts: sections.coverPrompts,
    onScreen: sections.onScreen,
    broll: sections.broll,
    caption: sections.caption,
    hashtags: sections.hashtags,
    notes: sections.notes,
  };
  return (
    <div className="shorts-workflow">
      <Column title="Plan">
        {cards.hooks && <WorkflowCard title="Hook Variations" body={cards.hooks.body} accent="#C41A18" />}
        {cards.titleVariants && <WorkflowCard title="Title / Thumbnail" body={cards.titleVariants.body} accent="#E0A458" />}
        {cards.coverPrompts && <WorkflowCard title="Cover Image Prompts" body={cards.coverPrompts.body} accent="#E7B23C" copyable />}
      </Column>
      <Column title="Script" wide>
        <PhoneFrame scriptBody={sections.shortScript?.body || ''} platform={platform} />
      </Column>
      <Column title="Distribute">
        {cards.caption && <WorkflowCard title="Caption" body={cards.caption.body} accent="#5BA0F2" />}
        {cards.hashtags && <HashtagCard body={cards.hashtags.body} />}
        {cards.onScreen && <WorkflowCard title="On-Screen Text" body={cards.onScreen.body} accent="#7F77DD" />}
        {cards.broll && <WorkflowCard title="B-Roll Shot List" body={cards.broll.body} accent="#378ADD" />}
        {cards.notes && <WorkflowCard title="Production Notes" body={cards.notes.body} accent="#C9956C" />}
      </Column>
    </div>
  );
}

function Column({ title, wide, children }) {
  return (
    <div className={`workflow-col ${wide ? 'workflow-col-wide' : ''}`}>
      <h3 className="workflow-col-title">{title}</h3>
      <div className="workflow-col-body">{children}</div>
    </div>
  );
}

function WorkflowCard({ title, body, accent, copyable }) {
  return (
    <article className="workflow-card" style={{ '--wf-accent': accent }}>
      <header className="workflow-card-head">
        <span className="workflow-card-title">{title}</span>
        {copyable && <CopyOnly text={body} />}
      </header>
      <div className="workflow-card-body">{body}</div>
    </article>
  );
}

function HashtagCard({ body }) {
  const tags = (body || '')
    .split(/\s+/)
    .filter((t) => t.startsWith('#'))
    .slice(0, 30);
  if (!tags.length) {
    return <WorkflowCard title="Hashtags" body={body} accent="#9C6DD1" />;
  }
  return (
    <article className="workflow-card" style={{ '--wf-accent': '#9C6DD1' }}>
      <header className="workflow-card-head">
        <span className="workflow-card-title">Hashtags</span>
        <CopyOnly text={tags.join(' ')} />
      </header>
      <div className="hashtag-chips">
        {tags.map((t, i) => <ClickToCopyTag key={i} tag={t} />)}
      </div>
    </article>
  );
}

function ClickToCopyTag({ tag }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(tag);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  return (
    <button type="button" className={`hashtag-chip ${copied ? 'is-copied' : ''}`} onClick={copy}>
      {copied ? '✓ copied' : tag}
    </button>
  );
}

function CopyOnly({ text, label, className }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  return (
    <button
      type="button"
      className={`copy-btn copy-btn-mini ${className || ''}`}
      onClick={copy}
    >
      {copied ? '✓ Copied' : label || 'Copy'}
    </button>
  );
}
