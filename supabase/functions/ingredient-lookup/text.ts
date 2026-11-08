// Text helpers for ingredient lookup: normalisation, similarity, and the match mode a term should use.

/**
 * A Wikidata label without the bracket Wikidata adds to tell items apart, which no notice ever writes
 * (8 November 2026, ginkgo): "Ginkgo biloba (farmacología)" → Ginkgo biloba, "Ginkgo (feuille de)" → Ginkgo.
 * A label that is nothing but a bracket is kept as it is.
 */
export function plainLabel(s: string): string {
  const t = s.replace(/\s*\([^()]*\)\s*$/u, "").trim();
  return t || s.trim();
}

/** NFKC, case-folded, accents stripped, spaces and hyphens removed — for comparing names, never for storage. */
export function squash(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[\s\-‐-―_.'’]+/g, "");
}

/** Lower-case, accent-free form with single spaces — the key used to merge names. */
export function key(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/\p{M}+/gu, "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
    }
    prev = cur;
  }
  return prev[b.length];
}

function trigrams(s: string): Set<string> {
  const p = `  ${s} `;
  const out = new Set<string>();
  for (let i = 0; i < p.length - 2; i++) out.add(p.slice(i, i + 3));
  return out;
}

/** 0..1: the better of edit-distance similarity and trigram Dice, on squashed strings. */
export function similarity(a: string, b: string): number {
  const x = squash(a);
  const y = squash(b);
  if (!x || !y) return 0;
  if (x === y) return 1;
  const lev = 1 - levenshtein(x, y) / Math.max(x.length, y.length);
  const tx = trigrams(x);
  const ty = trigrams(y);
  let common = 0;
  for (const t of tx) if (ty.has(t)) common++;
  const dice = (2 * common) / (tx.size + ty.size);
  return Math.max(lev, dice);
}

const NON_LATIN_SUBSTRING = /[぀-ヿㇰ-ㇿ㐀-鿿豈-﫿가-힯ᄀ-ᇿ؀-ۿݐ-ݿ]/;

/**
 * Match mode for a proposed term:
 * - Japanese, Korean, Chinese and Arabic script → substring (no spaces between words; Arabic prefixes attach);
 * - short codes (4 characters or fewer, or code-like) → exact;
 * - every other (Latin-script) term → stem (word start plus up to 6 suffix characters, for inflections).
 */
export function modeFor(term: string, lang: string, kind: string): "stem" | "exact" | "substring" {
  if (["ja", "ko", "zh", "ar"].includes(lang) || NON_LATIN_SUBSTRING.test(term)) return "substring";
  if (kind === "code" || term.replace(/\s/g, "").length <= 4) return "exact";
  return "stem";
}

/** Development codes such as "Ro 13-9297", "HN-10000", "TS-110". */
export function looksLikeCode(s: string): boolean {
  return /^[A-Z]{1,5}[- ]?\d{2,6}(?:[- ]\d{1,6})?[A-Z]?$/i.test(s.trim()) && /\d/.test(s);
}

/** Names worth proposing as a matchable term (drops IUPAC names, registry numbers and catalogue ids). */
export function usableSynonym(s: string): boolean {
  const t = s.trim();
  if (t.length < 3 || t.length > 40) return false;
  if (/[\[\](){},;:=]/.test(t)) return false;
  if (/^\d+-\d+-\d$/.test(t)) return false; // CAS number
  if (/^C\d*H\d*(?:[A-Z][a-z]?\d*)*$/.test(t) && /\d/.test(t)) return false; // formula (C9H13NO2)
  if (/^[A-Z0-9]{10}$/.test(t) && /\d/.test(t)) return false; // UNII
  if (/^(CHEBI|CHEMBL|DTXSID|DTXCID|SCHEMBL|ZINC|AKOS|MFCD|NSC|CCRIS|HSDB|EINECS|UNII|BRN|HY-|CS-|BDBM|SR-|KS-|AC-|AB\d|NCGC|BRD|SBI|Q\d|D\d{5}|RefChem|BIDD|GTPL|s\d{4})/i.test(t)) {
    return false;
  }
  if (/\b(impurity|metabolite|hydroxy|-d\d|standard|reference|usp|ep|bp|jan|inn|ban|dcf|dcit|usan)\b/i.test(t)) {
    return false;
  }
  return true;
}
