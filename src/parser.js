// Parse the model's markdown into named sections keyed by the `### ` header.
// Returns an object with up to four sections: concept, script, broll, notes.
export function parseSections(raw) {
  if (!raw) return {};
  const lines = raw.split('\n');
  const sections = {};
  let current = null;
  let buffer = [];

  const flush = () => {
    if (current) sections[current.key] = { title: current.title, body: buffer.join('\n').trim() };
    buffer = [];
  };

  for (const line of lines) {
    const headerMatch = line.match(/^###\s+(.*)$/);
    if (headerMatch) {
      flush();
      const title = headerMatch[1].trim();
      const key = classify(title);
      current = { key, title };
    } else if (current) {
      buffer.push(line);
    }
  }
  flush();
  return sections;
}

function classify(title) {
  const t = title.toUpperCase();
  if (t.includes('VIDEO CONCEPT')) return 'concept';
  if (t.includes('NARRATION') || t.includes('SCRIPT')) return 'script';
  if (t.includes('B-ROLL') || t.includes('BROLL')) return 'broll';
  if (t.includes('PRODUCTION')) return 'notes';
  return title.toLowerCase().replace(/[^a-z0-9]+/g, '_');
}
