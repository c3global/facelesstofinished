import React from 'react';

// Lightweight markdown renderer for the subset the model emits:
// **bold**, line breaks, and paragraph spacing. Avoids pulling in a
// full markdown library for what is essentially formatted narration.
export default function Markdown({ text }) {
  if (!text) return null;
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, i) => (
        <p key={i} className="md-block">
          {renderInline(block)}
        </p>
      ))}
    </>
  );
}

function renderInline(block) {
  const lines = block.split('\n');
  return lines.map((line, li) => (
    <React.Fragment key={li}>
      {renderBold(line)}
      {li < lines.length - 1 && <br />}
    </React.Fragment>
  ));
}

function renderBold(line) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}
