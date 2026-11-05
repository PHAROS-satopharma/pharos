// Pure helpers for the live NCBI counts: is the date range one the literature-search function accepts?

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** A real calendar day written YYYY-MM-DD. */
export function isDay(value: string | null | undefined): boolean {
  const m = DAY_RE.exec(value ?? '');
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}

/** What is wrong with a range of publication dates, in her words; null when NCBI can be asked. */
export function rangeProblem(from: string | null | undefined, to: string | null | undefined): string | null {
  if (!isDay(from) || !isDay(to)) return 'Give both dates.';
  if ((from as string) > (to as string)) return 'The first date is after the last one.';
  if ((from as string) < '1800-01-01') return 'The first date is too early.';
  return null;
}

/** The react-query key of one ingredient's counts for one range. */
export function literatureSearchKey(ingredientId: string, from: string, to: string): readonly unknown[] {
  return ['literature-search', ingredientId, from, to] as const;
}
