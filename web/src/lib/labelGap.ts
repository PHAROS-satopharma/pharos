// Our label against an originator's label change: which of the sentences the originator added does our
// label already say? Plain word overlap, in one language, explained on screen; never a translation.

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
    .replace(/[ 　]/g, ' ')
    .replace(/-\s*\n\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** The EU SmPC section an originator's section corresponds to (US PI and Japanese headings mapped). */
export function euSection(key: string): string | null {
  if (/^\d/.test(key)) return key.split('.').slice(0, 2).join('.');
  const map: Record<string, string> = {
    'us:boxed_warning': '4.4',
    'us:contraindications': '4.3',
    'us:warnings_and_precautions': '4.4',
    'us:warnings': '4.4',
    'us:adverse_reactions': '4.8',
    'us:drug_interactions': '4.5',
    'us:specific_populations': '4.6',
    'us:overdosage': '4.9',
    'us:indications': '4.1',
    'us:dosage_and_administration': '4.2',
    'ja:1': '4.4',
    'ja:2': '4.3',
    'ja:8': '4.4',
    'ja:9': '4.4',
    'ja:10': '4.5',
    'ja:11': '4.8',
    'ja:13': '4.9',
    'ja:precautions': '4.4',
  };
  return map[key] ?? null;
}

/** Sentences, split after . ; ! ? or a line break; short fragments (headings, bullets) are dropped. */
export function sentences(text: string): string[] {
  return normalize(text)
    .split(/(?<=[.;!?。])\s+|\s+[•▪·]\s+/)
    .map((s) => s.trim())
    .filter((s) => s.replace(/[^\p{L}]/gu, '').length >= 12);
}

/** The sentences of `after` that are not in `before` (compared whitespace- and case-insensitively). */
export function addedSentences(before: string, after: string): string[] {
  const had = new Set(sentences(before).map((s) => s.toLowerCase()));
  return sentences(after).filter((s) => !had.has(s.toLowerCase()));
}

const STOP = new Set(
  (
    'the and for with that this from have been were which when what will shall should would could may might must ' +
    'also into than then there their these those such other some more most very only each both after before ' +
    'during while about above below between under over again further once here where your patients patient ' +
    'treatment taking take taken used using dose doses product medicine medicinal'
  ).split(' '),
);

/** Content words: letters only, four or more, a plural -s dropped, common words left out. */
export function contentWords(s: string): Set<string> {
  const out = new Set<string>();
  for (const raw of s.toLowerCase().match(/\p{L}+/gu) ?? []) {
    if (raw.length < 4 || STOP.has(raw)) continue;
    out.add(raw.length > 4 && raw.endsWith('s') && !raw.endsWith('ss') ? raw.slice(0, -1) : raw);
  }
  return out;
}

export type GapStatus = 'covered' | 'partly' | 'missing';

export interface GapResult {
  sentence: string;
  status: GapStatus;
  /** Share of the sentence's content words found in our closest sentence, 0–1. */
  score: number;
  /** Our closest sentence, when any word is shared. */
  closest: string | null;
}

/** For each sentence the originator added, how much of it our section already says. */
export function compareWithOurs(added: string[], ours: string): GapResult[] {
  const our = sentences(ours).map((s) => ({ s, w: contentWords(s) }));
  return added.map((sentence) => {
    const w = contentWords(sentence);
    let best = 0;
    let closest: string | null = null;
    for (const o of our) {
      if (w.size === 0) break;
      let shared = 0;
      for (const x of w) if (o.w.has(x)) shared++;
      const score = shared / w.size;
      if (score > best) {
        best = score;
        closest = o.s;
      }
    }
    const status: GapStatus = best >= 0.75 ? 'covered' : best >= 0.4 ? 'partly' : 'missing';
    return { sentence, status, score: Math.round(best * 100) / 100, closest: best > 0 ? closest : null };
  });
}

/** Whether two BCP-47 codes are the same language ("en" and "en-GB" are). */
export function sameLanguage(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  return a.toLowerCase().split('-')[0] === b.toLowerCase().split('-')[0];
}
