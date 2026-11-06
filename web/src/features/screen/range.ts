// The days the Ingredients screen looks at: Cairo calendar days, both included, at most 366. Pure helpers.

import { CAIRO, formatDate } from '../../lib/format';
import { isDay } from '../literature/literatureRange';

export type RangePreset = 'this-week' | 'last-week' | 'last-30' | 'custom';

export interface DayRange {
  from: string;
  to: string;
  preset: RangePreset;
}

/** The most days one screen asks for (the database refuses more). */
export const MAX_DAYS = 366;

export const PRESETS: { key: Exclude<RangePreset, 'custom'>; label: string }[] = [
  { key: 'this-week', label: 'This week' },
  { key: 'last-week', label: 'Last week' },
  { key: 'last-30', label: 'Last 30 days' },
];

const cairoDayFmt = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: CAIRO,
});

/** The Cairo calendar day of an instant, YYYY-MM-DD. */
export function cairoDayOf(now: Date): string {
  const parts = cairoDayFmt.formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

function toUtc(day: string): number {
  return Date.UTC(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)));
}

/** The day `n` days after `day` (before it when negative). */
export function addDays(day: string, n: number): string {
  return new Date(toUtc(day) + n * 86_400_000).toISOString().slice(0, 10);
}

/** How many days from `from` to `to`, both included. */
export function dayCount(from: string, to: string): number {
  return Math.round((toUtc(to) - toUtc(from)) / 86_400_000) + 1;
}

/** Sunday of the week that holds `day` (weeks run Sunday to Saturday, as on the Sources screen). */
export function weekStartOf(day: string): string {
  return addDays(day, -new Date(toUtc(day)).getUTCDay());
}

/** The days of a preset, as seen on Cairo day `today`. This week runs from Sunday to today. */
export function presetDays(preset: Exclude<RangePreset, 'custom'>, today: string): { from: string; to: string } {
  const sunday = weekStartOf(today);
  if (preset === 'last-week') return { from: addDays(sunday, -7), to: addDays(sunday, -1) };
  if (preset === 'last-30') return { from: addDays(today, -29), to: today };
  return { from: sunday, to: today };
}

/** What is wrong with a range of days, in plain words; null when it can be asked for. */
export function rangeError(from: string | null | undefined, to: string | null | undefined): string | null {
  if (!isDay(from) || !isDay(to)) return 'Give both days.';
  if ((to as string) < (from as string)) return 'The last day is before the first.';
  if (dayCount(from as string, to as string) > MAX_DAYS) return `Choose at most ${MAX_DAYS} days.`;
  return null;
}

/** The days in the address (`?from=&to=`), else this week. A preset is recognised from its days. */
export function rangeFromSearch(search: URLSearchParams, today: string): DayRange {
  const from = search.get('from');
  const to = search.get('to');
  if (from && to && rangeError(from, to) === null) return { from, to, preset: presetOf(from, to, today) };
  return { ...presetDays('this-week', today), preset: 'this-week' };
}

/** Which preset these days are, as seen on `today`; 'custom' when none. */
export function presetOf(from: string, to: string, today: string): RangePreset {
  for (const p of PRESETS) {
    const d = presetDays(p.key, today);
    if (d.from === from && d.to === to) return p.key;
  }
  return 'custom';
}

/** "1 Nov 2026 – 6 Nov 2026", or one day. */
export function rangeLabel(from: string, to: string): string {
  return from === to ? formatDate(from) : `${formatDate(from)} – ${formatDate(to)}`;
}
