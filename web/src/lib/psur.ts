// The EURD reporting interval of an ingredient, as EMA's list sets it (eurd_entry, 0028). The PSUR pack on Reports
// (features/reports/Packs.tsx) starts from it; collectors/report_pack.py (interval_for) works it out the same way.
// Pure helpers, no I/O.

/** One row of EMA's EURD list for an ingredient, as eurd_entry holds it. */
export interface EurdEntry {
  eurd_id: number;
  ingredient_id: string;
  substance: string;
  combination: boolean;
  frequency: string | null;
  dlp: string | null;
  submission_date: string | null;
  next_dlp: string | null;
  next_submission_date: string | null;
  list_version: string;
  list_date: string | null;
}

/** "7 years" → 84, "6 months" → 6; null for anything else ("Not applicable", blank). */
export function frequencyMonths(frequency: string | null | undefined): number | null {
  const m = /^\s*(\d{1,2})\s*(year|month)s?\b/i.exec(frequency ?? '');
  if (!m) return null;
  return Number(m[1]) * (m[2].toLowerCase() === 'year' ? 12 : 1);
}

/** The same calendar day `months` later (or earlier), kept within the month: 31 Aug + 6 months is 28 Feb. */
export function addMonths(day: string, months: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, last));
  return target.toISOString().slice(0, 10);
}

export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d) + n * 86_400_000).toISOString().slice(0, 10);
}

/**
 * The reporting interval that ends at the EURD data lock point: the day after the previous DLP (one frequency
 * earlier) to the DLP itself. Null when the row has no DLP or no frequency in months or years.
 */
export function intervalFor(entry: Pick<EurdEntry, 'dlp' | 'frequency'>): { from: string; to: string } | null {
  const months = frequencyMonths(entry.frequency);
  if (!entry.dlp || !months) return null;
  return { from: addDays(addMonths(entry.dlp, -months), 1), to: entry.dlp };
}
