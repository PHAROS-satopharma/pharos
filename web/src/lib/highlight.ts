// Offset-based highlighting of matched words in an original text. Pure functions, no DOM.
// The collectors store match offsets into the original text (document_text.text, or the original
// title); when offsets are missing or do not fit, the matched words are searched for instead.

export interface TextRange {
  start: number;
  end: number;
}

export interface Segment {
  text: string;
  mark: boolean;
  /** Offset of this segment in the full text. */
  start: number;
}

export interface Excerpt {
  start: number;
  end: number;
  segments: Segment[];
  clippedStart: boolean;
  clippedEnd: boolean;
}

export interface OffsetMatch {
  start: number | null;
  end: number | null;
  text: string;
}

/** Clamps ranges to the text, drops empty or invalid ones, sorts them and merges overlaps. */
export function normalizeRanges(ranges: readonly TextRange[], length: number): TextRange[] {
  const clean = ranges
    .filter((r) => Number.isFinite(r.start) && Number.isFinite(r.end))
    .map((r) => ({
      start: Math.max(0, Math.min(length, Math.floor(r.start))),
      end: Math.max(0, Math.min(length, Math.floor(r.end))),
    }))
    .filter((r) => r.end > r.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const out: TextRange[] = [];
  for (const r of clean) {
    const last = out.length > 0 ? out[out.length - 1] : undefined;
    if (last && r.start <= last.end) last.end = Math.max(last.end, r.end);
    else out.push({ start: r.start, end: r.end });
  }
  return out;
}

/** Splits text[from, to) into plain and marked segments. */
export function segments(text: string, ranges: readonly TextRange[], from = 0, to: number = text.length): Segment[] {
  const lo = Math.max(0, Math.min(from, text.length));
  const hi = Math.max(lo, Math.min(to, text.length));
  const rs = normalizeRanges(ranges, text.length);
  const out: Segment[] = [];
  let pos = lo;
  for (const r of rs) {
    if (r.end <= lo) continue;
    if (r.start >= hi) break;
    const s = Math.max(r.start, lo);
    const e = Math.min(r.end, hi);
    if (s > pos) out.push({ text: text.slice(pos, s), mark: false, start: pos });
    out.push({ text: text.slice(s, e), mark: true, start: s });
    pos = e;
  }
  if (pos < hi) out.push({ text: text.slice(pos, hi), mark: false, start: pos });
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Every case-insensitive occurrence of needle in text, as offsets into the original text. */
export function findOccurrences(text: string, needle: string): TextRange[] {
  const n = needle.trim();
  if (!n || !text) return [];
  const re = new RegExp(escapeRegExp(n), 'giu');
  const out: TextRange[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m[0].length === 0) {
      re.lastIndex += 1;
      continue;
    }
    out.push({ start: m.index, end: m.index + m[0].length });
  }
  return out;
}

/** Uses each match's offsets when they fit the text, otherwise searches for its matched words. */
export function resolveRanges(text: string, matches: readonly OffsetMatch[]): TextRange[] {
  const out: TextRange[] = [];
  for (const m of matches) {
    if (m.start != null && m.end != null && m.start >= 0 && m.end > m.start && m.end <= text.length) {
      out.push({ start: m.start, end: m.end });
    } else if (m.text) {
      out.push(...findOccurrences(text, m.text));
    }
  }
  return normalizeRanges(out, text.length);
}

function isLowSurrogate(code: number): boolean {
  return code >= 0xdc00 && code <= 0xdfff;
}

const SPACE = /\s/;

function snapStart(text: string, s: number, limit: number): number {
  if (s <= 0) return 0;
  const stop = Math.min(limit, s + 24);
  for (let i = s; i < stop; i++) {
    if (SPACE.test(text.charAt(i))) return i + 1;
  }
  return isLowSurrogate(text.charCodeAt(s)) ? s + 1 : s;
}

function snapEnd(text: string, e: number, limit: number): number {
  if (e >= text.length) return text.length;
  const stop = Math.max(limit, e - 24);
  for (let i = e; i > stop; i--) {
    if (SPACE.test(text.charAt(i - 1))) return i - 1;
  }
  return isLowSurrogate(text.charCodeAt(e)) ? e + 1 : e;
}

/**
 * Short windows of text around each highlighted range, with `context` characters either side,
 * snapped to whitespace where it is close and never splitting a surrogate pair. Windows that
 * touch or overlap are merged into one.
 */
export function excerpts(text: string, ranges: readonly TextRange[], context = 160): Excerpt[] {
  const rs = normalizeRanges(ranges, text.length);
  const windows: TextRange[] = [];
  for (const r of rs) {
    const s = snapStart(text, Math.max(0, r.start - context), r.start);
    const e = snapEnd(text, Math.min(text.length, r.end + context), r.end);
    const last = windows.length > 0 ? windows[windows.length - 1] : undefined;
    if (last && s <= last.end) last.end = Math.max(last.end, e);
    else windows.push({ start: s, end: e });
  }
  return windows.map((w) => ({
    start: w.start,
    end: w.end,
    segments: segments(text, rs, w.start, w.end),
    clippedStart: w.start > 0,
    clippedEnd: w.end < text.length,
  }));
}
