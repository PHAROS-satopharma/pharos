// The Japan codes: PMDA's 一般名 codes, kept as ingredient_terms of kind 'code', country JP, so Japan's label watch
// can find the package inserts (collectors/spc/pmda_pi.py). PMDA files one ingredient under one code per form
// (paracetamol: 1141007 tablets, 1141700 suppositories, 1141400 injection), so an ingredient can have several. Set on
// an ingredient that exists by set_japan_codes() (migration 0069), which checks each by the same rule and stores the
// 7 characters. Pure, for JapanCodeField.tsx.
import { isJapanCode } from './readiness';

/** PMDA's search form (it answers a POST only; see docs/operations.md, "Adding an ingredient"). */
export const PMDA_SEARCH = 'https://www.pmda.go.jp/PmdaSearch/iyakuSearch/';

/** The page that lists every product under one code (Cravit and its generics under 6241013). */
export function pmdaGeneralListUrl(code: string): string {
  return `https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/${encodeURIComponent(code)}`;
}

/** The 7-character code to store, from the code or the 12-character YJ code that starts with it; null otherwise. */
export function japanCodeOf(input: string): string | null {
  const s = input.trim().toUpperCase();
  return isJapanCode(s) ? s.slice(0, 7) : null;
}

/** Every code typed in the field: separated by commas, spaces, new lines, Japanese commas or semicolons. Each is
 *  stored as its 7 characters, once; what is not a Japan code is named in `wrong`, as the field and the database
 *  refuse it. */
export function japanCodesOf(input: string): { codes: string[]; wrong: string[] } {
  const codes: string[] = [];
  const wrong: string[] = [];
  for (const part of input.split(/[\s,、;；]+/)) {
    if (!part) continue;
    const code = japanCodeOf(part);
    if (!code) wrong.push(part.toUpperCase());
    else if (!codes.includes(code)) codes.push(code);
  }
  return { codes, wrong };
}

/** The ingredient's current Japan codes, in order; empty when it has none. */
export function currentJapanCodes(terms: { kind: string; country_code: string | null; term: string }[]): string[] {
  return terms
    .filter((t) => t.kind === 'code' && t.country_code === 'JP')
    .map((t) => t.term)
    .sort();
}

/** True when the codes typed are the ones saved, whatever their order. */
export function sameJapanCodes(a: string[], b: string[]): boolean {
  const x = [...a].sort();
  const y = [...b].sort();
  return x.length === y.length && x.every((c, i) => c === y[i]);
}

export interface LocalTerm {
  term: string;
  isCode: boolean;
  /** The country's name. */
  where: string;
}

/** The terms that apply in one country only, for the Ingredients list's "Local codes" column. Every other name is
 *  looked for in every country that writes its language; today the only local term is the Japan code, so a column
 *  headed "Country-specific names" that said "Japan" on every row read as if PHAROS watched Japan only (6 Nov 2026).
 *  The column shows the code itself and what it is for. */
export function localTerms(
  terms: { kind: string; country_code: string | null; term: string }[],
  nameOf: (code: string) => string,
): LocalTerm[] {
  return terms
    .filter((t): t is { kind: string; country_code: string; term: string } => Boolean(t.country_code))
    .map((t) => ({ term: t.term, isCode: t.kind === 'code', where: nameOf(t.country_code) }))
    .sort((a, b) => a.where.localeCompare(b.where) || a.term.localeCompare(b.term));
}
