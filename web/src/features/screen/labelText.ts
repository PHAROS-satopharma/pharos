// The text of our label, split into its numbered sections before it is saved (save_our_label). The comparison
// with an originator's label change is no longer done here: the collector computes it (collectors/labels) and
// label_changes() hands it to the screen.

/** Valid QRD numbers, as collectors/spc/sections.py: 1–10, 2.1–2.2, 4.1–4.9, 5.1–5.3, 6.1–6.6. */
const VALID = new Set<string>([
  ...Array.from({ length: 10 }, (_, i) => String(i + 1)),
  '2.1',
  '2.2',
  ...Array.from({ length: 9 }, (_, i) => `4.${i + 1}`),
  ...Array.from({ length: 3 }, (_, i) => `5.${i + 1}`),
  ...Array.from({ length: 6 }, (_, i) => `6.${i + 1}`),
]);
const HEAD = /^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.{0,200})$/;

function numKey(n: string): number[] {
  return n.split('.').map(Number);
}

function after(a: number[], b: number[] | null): boolean {
  if (!b) return true;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] ?? -1;
    const y = b[i] ?? -1;
    if (x !== y) return x > y;
  }
  return false;
}

/**
 * Splits an SmPC / leaflet text into its numbered sections ("4.4" → text). A heading is a valid QRD number
 * at the start of a line, later in order than the one before it, so a numbered list inside a section
 * ("1. Take with food") never starts a new section. Third-level headings (4.2.1) stay inside their section.
 */
export function splitSections(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  let current: string | null = null;
  let last: number[] | null = null;
  for (const line of text.replace(/\r\n?/g, '\n').split('\n')) {
    const m = HEAD.exec(line);
    if (m) {
      const parts = m[1].split('.');
      const key = parts.slice(0, 2).join('.');
      const k = numKey(m[1]);
      if (VALID.has(key) && after(k, last)) {
        last = k;
        if (parts.length <= 2) {
          current = key;
          out[current] = out[current] ? `${out[current]}\n` : '';
          continue;
        }
      }
    }
    if (current) out[current] = out[current] ? `${out[current]}\n${line}` : line;
  }
  for (const k of Object.keys(out)) {
    out[k] = normalize(out[k]);
    if (!out[k]) delete out[k];
  }
  return out;
}

/** Whitespace-insensitive text, with line-end hyphenation from PDF extraction joined. */
export function normalize(t: string): string {
  return t
    .replace(/[ 　]/g, ' ')
    .replace(/-\s*\n\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Section numbers in their numeric order: 1, 4.1, 4.4, 4.8, 10. */
export function sectionOrder(a: string, b: string): number {
  const x = numKey(a);
  const y = numKey(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] ?? -1) - (y[i] ?? -1);
    if (d !== 0) return d;
  }
  return 0;
}
