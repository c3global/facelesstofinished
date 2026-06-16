import React, { useState } from "react";
import { Copy, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const SECTION_LABEL = {
  angles: "Topic Angles", concept: "Video Concept", hooks: "Hook Variations",
  outline: "Outline", script: "Narration Script", transitions: "Transitions",
  broll: "B-Roll Shot List", notes: "Production Notes",
  shortScript: "Short-Form Script", onScreen: "On-Screen Text",
  caption: "Caption", hashtags: "Hashtags",
  titleVariants: "Title / Thumbnail Variants", coverPrompts: "Cover Image Prompts",
};

export function CopyButton({ text, testid }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy-btn"
      data-testid={testid}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {}
      }}
    >
      <Copy size={12} /> {copied ? "Copied!" : "Copy"}
    </button>
  );
}

/**
 * SectionCard — collapsible script section (v1.8.0 mirror).
 *
 * Clicking the header collapses/expands the body. Collapsed state is OWNED
 * by the parent (`collapsed` prop + `onToggle` callback) so the global
 * "Collapse all / Expand all" toggle in the sticky nav bar can flip every
 * card at once. Body is preserved while collapsed — no markdown re-render
 * cost when the user toggles it back open.
 */
export function SectionCard({ keyName, section, testid, revealIndex, collapsed = false, onToggle }) {
  if (!section) return null;
  const style = revealIndex != null ? { animationDelay: `${revealIndex * 90}ms` } : undefined;
  const headerProps = onToggle
    ? {
        role: "button",
        tabIndex: 0,
        onClick: () => onToggle(keyName),
        onKeyDown: (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle(keyName);
          }
        },
        "aria-expanded": !collapsed,
      }
    : {};
  return (
    <section
      id={`section-${keyName}`}
      className={`section-card${revealIndex != null ? " section-card-reveal" : ""}${collapsed ? " is-collapsed" : ""}`}
      data-testid={testid}
      data-section={keyName}
      style={style}
    >
      <header
        className={`section-card-head${onToggle ? " is-clickable" : ""}`}
        data-testid={`${testid}-header`}
        {...headerProps}
      >
        <div className="section-card-head-left">
          {onToggle && (
            <ChevronDown
              size={14}
              className={`section-card-chevron${collapsed ? " is-collapsed" : ""}`}
              aria-hidden="true"
            />
          )}
          <h3 className="section-card-title">{SECTION_LABEL[keyName] || section.title}</h3>
        </div>
        <CopyButton text={section.body} testid={`${testid}-copy`} />
      </header>
      {!collapsed && (
        <div className="section-card-body markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
        </div>
      )}
    </section>
  );
}

export function SkeletonCard({ keyName }) {
  return (
    <section className="section-card section-card-skeleton" data-testid={`skeleton-${keyName}`} aria-hidden="true">
      <header className="section-card-head"><div className="skeleton-bar skeleton-bar-title" /></header>
      <div className="section-card-body">
        <div className="skeleton-bar" style={{ width: "92%" }} />
        <div className="skeleton-bar" style={{ width: "78%" }} />
        <div className="skeleton-bar" style={{ width: "85%" }} />
        <div className="skeleton-bar" style={{ width: "60%" }} />
      </div>
    </section>
  );
}
