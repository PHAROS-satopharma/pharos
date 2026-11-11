import type { LookupCandidate } from '../../lib/types';

/** Watched already: the same ATC code, or, for an ingredient with none (a herbal such as Ivy leaf), the same name. */
export function alreadyWatched(
  c: Pick<LookupCandidate, 'inn_en' | 'atc_code'>,
  atcCodes: Set<string>,
  names: Set<string>,
): boolean {
  return c.atc_code ? atcCodes.has(c.atc_code) : names.has(c.inn_en.trim().toLowerCase());
}
