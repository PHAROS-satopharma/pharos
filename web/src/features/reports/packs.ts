// Packs on request (the QPPV plan, phase 15): a PSUR pack for one ingredient, or an inspection pack, asked for on
// Reports with request_report() (0048) and made by the next collection run (collectors/report_pack.py). Pure
// helpers, no I/O.

import { addDays, addMonths, intervalFor, type EurdEntry } from '../../lib/psur';

export type PackKind = 'psur' | 'inspection';
export type PackStatus = 'queued' | 'building' | 'done' | 'failed';

/** A request as the report_request table holds it. */
export interface PackRequest {
  id: string;
  kind: PackKind;
  ingredient_id: string | null;
  from_day: string;
  to_day: string;
  requested_by: string;
  requested_at: string;
  status: PackStatus;
  error: string | null;
  attempts: number;
  started_at: string | null;
  pdf_r2_key: string | null;
  pdf_sha256: string | null;
  xlsx_r2_key: string | null;
  xlsx_sha256: string | null;
  made_at: string | null;
  git_sha: string | null;
  made_by_run: string | null;
}

export const PACK_NAME: Record<PackKind, string> = { psur: 'PSUR pack', inspection: 'Inspection pack' };

/** The packs she may ask for: an inspection pack is for administrators only (request_report, 0048). */
export function kindOptions(isAdmin: boolean): { value: PackKind; label: string }[] {
  const options: { value: PackKind; label: string }[] = [{ value: 'psur', label: 'PSUR pack: one ingredient' }];
  if (isAdmin) options.push({ value: 'inspection', label: 'Inspection pack: the whole system' });
  return options;
}

/** The packs listed to her: a reviewer or a reader sees PSUR packs only (the database reads them the same way). */
export function packsFor<T extends Pick<PackRequest, 'kind'>>(rows: T[], isAdmin: boolean): T[] {
  return isAdmin ? rows : rows.filter((r) => r.kind === 'psur');
}

/** The most a pack covers (the database refuses more). */
export const MAX_YEARS = 5;

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2 Dec 2024" for a calendar day, as the pack itself writes it. */
export function dayText(day: string): string {
  return `${Number(day.slice(8, 10))} ${MONTHS[Number(day.slice(5, 7)) - 1] ?? ''} ${day.slice(0, 4)}`;
}

/** "2 Dec 2024 – 6 Nov 2026". */
export function daysLabel(from: string, to: string): string {
  return `${dayText(from)} – ${dayText(to)}`;
}

/** "PSUR pack, levofloxacin, 2 Dec 2024 – 6 Nov 2026" / "Inspection pack, 7 Nov 2025 – 6 Nov 2026". */
export function packLabel(r: Pick<PackRequest, 'kind' | 'from_day' | 'to_day'>, ingredient?: string | null): string {
  const parts = [PACK_NAME[r.kind]];
  if (r.kind === 'psur' && ingredient) parts.push(ingredient);
  parts.push(daysLabel(r.from_day, r.to_day));
  return parts.join(', ');
}

/** The last 12 months to Cairo day `today`, both included: the inspection pack's days unless she changes them. */
export function lastTwelveMonths(today: string): { from: string; to: string } {
  return { from: addDays(addMonths(today, -12), 1), to: today };
}

/**
 * The PSUR pack's days unless she changes them: the EURD interval of the ingredient (its first row with one), cut
 * at `today` (a pack reads only days that have passed) and at five years. Without an interval, or one that has
 * not started yet, the last 12 months.
 */
export function psurDays(
  entries: ReadonlyArray<Pick<EurdEntry, 'dlp' | 'frequency'> & Partial<Pick<EurdEntry, 'next_dlp'>>>,
  today: string,
): { from: string; to: string; fromEurd: boolean } {
  const iv = entries.map(intervalFor).find((x) => x !== null) ?? null;
  if (!iv || iv.from > today) return { ...lastTwelveMonths(today), fromEurd: false };
  const to = iv.to < today ? iv.to : today;
  const earliest = addDays(addMonths(to, -12 * MAX_YEARS), 1);
  return { from: iv.from < earliest ? earliest : iv.from, to, fromEurd: true };
}

/** Why the days cannot be asked for, in her words, or null when they can (the checks request_report() makes). */
export function daysProblem(from: string, to: string, today: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) return 'Choose the first and the last day.';
  if (to < from) return 'The last day is before the first.';
  if (from > today) return 'The first day is in the future.';
  if (to > addMonths(from, 12 * MAX_YEARS)) return 'A pack covers at most five years.';
  return null;
}

/** Where the request stands, in one line. */
export function statusText(r: Pick<PackRequest, 'status' | 'error' | 'attempts'>): string {
  switch (r.status) {
    case 'queued':
      return r.error ? `Waiting: ${r.error}` : 'Waiting for the next collection run (within four hours)';
    case 'building':
      return 'Being made now';
    case 'done':
      return 'Made';
    case 'failed':
      return `Not made: ${r.error ?? 'the reason was not recorded'}`;
  }
}

function slug(text: string): string {
  return text.replace(/[^A-Za-z0-9-]+/g, '-').replace(/^-+|-+$/g, '') || 'pack';
}

/**
 * The name the file is saved under, as the collector archives it: "PHAROS-PSUR-levofloxacin-2024-12-02-to-2026-11-06.pdf",
 * "PHAROS-inspection-2025-11-07-to-2026-11-06.xlsx".
 */
export function packFileName(
  r: Pick<PackRequest, 'kind' | 'from_day' | 'to_day'>,
  ingredient: string | null | undefined,
  ext: 'pdf' | 'xlsx',
): string {
  const days = `${r.from_day.slice(0, 10)}-to-${r.to_day.slice(0, 10)}`;
  const stem = r.kind === 'psur' ? `PHAROS-PSUR-${slug(ingredient ?? 'ingredient')}-${days}` : `PHAROS-inspection-${days}`;
  return `${stem}.${ext}`;
}

/** Newest request first. */
export function newestFirst<T extends { requested_at: string; id: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.requested_at.localeCompare(a.requested_at) || b.id.localeCompare(a.id));
}

/** A request still on its way: the list is read again until it is made. */
export function stillWaiting(rows: ReadonlyArray<Pick<PackRequest, 'status'>>): boolean {
  return rows.some((r) => r.status === 'queued' || r.status === 'building');
}
