import React, { useState } from "react";
import { Copy } from "lucide-react";
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
      type="button" className="copy-btn" data-testid={testid}
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {}
      }}
    >
      <Copy size={12} /> {copied ? "Copied!" : "Copy"}
    </button>
  );
}

export function SectionCard({ keyName, section, testid }) {
  if (!section) return null;
  return (
    <section className="section-card" data-testid={testid}>
      <header className="section-card-head">
        <h3 className="section-card-title">{SECTION_LABEL[keyName] || section.title}</h3>
        <CopyButton text={section.body} testid={`${testid}-copy`} />
      </header>
      <div className="section-card-body markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
      </div>
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
