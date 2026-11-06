// The weeks of the weekly report: Cairo calendar weeks, Sunday to Saturday (Dr Sama's review, 6 Nov 2026), as
// collectors/report_weekly.py makes them. Pure helpers, no I/O.

import { addDays, weekStartOf } from '../screen/range';

/** The first week PHAROS screened in full: its first check ran on Thursday 5 November 2026. */
export const FIRST_WEEK = '2026-11-01';

/** A weekly report as the weekly_report table holds it. */
export interface WeeklyReport {
  id: string;
  week_start: string;
  week_end: string;
  xlsx_r2_key: string;
  xlsx_sha256: string;
  pdf_r2_key: string;
  pdf_sha256: string;
  made_at: string;
  git_sha: string | null;
  made_by_run: string | null;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function parts(day: string): { y: string; m: string; d: number } {
  return { y: day.slice(0, 4), m: MONTHS[Number(day.slice(5, 7)) - 1] ?? '', d: Number(day.slice(8, 10)) };
}

/** "Sun 1 Nov – Sat 7 Nov 2026"; the first year is written only when the week crosses into a new one (as the
 *  report's own label). */
export function weekLabel(sunday: string): string {
  const a = parts(sunday);
  const b = parts(addDays(sunday, 6));
  return `Sun ${a.d} ${a.m}${a.y !== b.y ? ` ${a.y}` : ''} – Sat ${b.d} ${b.m} ${b.y}`;
}

/** The days of the week starting on `sunday`, both included, for screening_log(). */
export function weekDays(sunday: string): { from: string; to: string } {
  return { from: sunday, to: addDays(sunday, 6) };
}

/** The last week that has ended on Cairo day `today`, never before the first week PHAROS screened. */
export function lastCompleteWeek(today: string): string {
  const last = addDays(weekStartOf(today), -7);
  return last < FIRST_WEEK ? FIRST_WEEK : last;
}

/** The weeks to choose from on Cairo day `today`: this week (so far) first, back to the first week. */
export function weekOptions(today: string): { value: string; label: string }[] {
  const current = weekStartOf(today);
  const out: { value: string; label: string }[] = [];
  for (let w = current; w >= FIRST_WEEK; w = addDays(w, -7)) {
    out.push({ value: w, label: w === current ? `${weekLabel(w)} (this week, so far)` : weekLabel(w) });
  }
  return out;
}

/** "PHAROS-weekly-2026-11-01.pdf": the week's Sunday, in the name the file is saved under. */
export function weeklyFileName(sunday: string, ext: 'xlsx' | 'pdf'): string {
  return `PHAROS-weekly-${sunday.slice(0, 10)}.${ext}`;
}

/** Newest week first, for the list of reports. */
export function newestWeekFirst<T extends { week_start: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.week_start.localeCompare(a.week_start));
}
