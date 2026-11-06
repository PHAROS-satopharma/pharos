// The Japan code: PMDA's 一般名 code, kept as an ingredient_term of kind 'code', country JP, so Japan's label watch
// can find the package inserts (collectors/spc/pmda_pi.py). Set on an ingredient that exists by set_japan_code()
// (migration 0052), which checks it by the same rule and stores the 7 characters. Pure, for JapanCodeField.tsx.
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

/** The ingredient's current Japan code, or null when it has none. */
export function currentJapanCode(terms: { kind: string; country_code: string | null; term: string }[]): string | null {
  const codes = terms
    .filter((t) => t.kind === 'code' && t.country_code === 'JP')
    .map((t) => t.term)
    .sort();
  return codes[0] ?? null;
}
