// Dates are stored in UTC and shown in Cairo local time. A published date (a calendar day with no
// time) is shown as the day the regulator printed, with no time-zone shift.

export const CAIRO = 'Africa/Cairo';

const dayFmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const monthFmt = new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });
const dateTimeFmt = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: CAIRO,
});
const partsFmt = new Intl.DateTimeFormat('en-GB', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
  timeZone: CAIRO,
});

function parseDay(d: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  if (!m) return null;
  return new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

/** "4 Nov 2026" for a calendar date (YYYY-MM-DD). */
export function formatDate(d: string | null | undefined): string {
  if (!d) return '—';
  const day = parseDay(d);
  return day ? dayFmt.format(day) : d;
}

/** "October 2026" for the first day of a month. */
export function formatMonth(d: string | null | undefined): string {
  if (!d) return '—';
  const day = parseDay(d);
  return day ? monthFmt.format(day) : d;
}

const cairoDayFmt = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: CAIRO });

/** "4 Nov 2026" — the Cairo calendar day of a stored timestamp. */
export function formatCairoDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  const t = new Date(ts);
  return Number.isNaN(t.getTime()) ? ts : cairoDayFmt.format(t);
}

/** "4 Nov 2026, 21:34" in Cairo for a stored timestamp. */
export function formatDateTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  const t = new Date(ts);
  if (Number.isNaN(t.getTime())) return ts;
  return dateTimeFmt.format(t);
}

/** "12 min ago", "5 h ago", "3 days ago". */
export function timeAgo(ts: string | null | undefined, now: number = Date.now()): string {
  if (!ts) return 'never';
  const t = new Date(ts).getTime();
  if (Number.isNaN(t)) return '—';
  const min = Math.round((now - t) / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  const days = Math.round(h / 24);
  return `${days} days ago`;
}

interface WallClock {
  y: number;
  m: number;
  d: number;
  h: number;
  min: number;
  s: number;
}

function cairoWall(instant: Date): WallClock {
  const get = (type: string): number => Number(partsFmt.formatToParts(instant).find((p) => p.type === type)?.value ?? 0);
  return { y: get('year'), m: get('month'), d: get('day'), h: get('hour'), min: get('minute'), s: get('second') };
}

function cairoOffsetMs(instant: Date): number {
  const w = cairoWall(instant);
  const asUtc = Date.UTC(w.y, w.m - 1, w.d, w.h, w.min, w.s);
  return asUtc - Math.floor(instant.getTime() / 1000) * 1000;
}

/** The UTC instant of midnight in Cairo on the given day (month is 1–12). */
export function cairoMidnightUtc(y: number, m: number, d: number): Date {
  const guess = Date.UTC(y, m - 1, d);
  let t = guess - cairoOffsetMs(new Date(guess));
  t = guess - cairoOffsetMs(new Date(t));
  return new Date(t);
}

/** Today's date in Cairo, YYYY-MM-DD. */
export function cairoToday(): string {
  const w = cairoWall(new Date());
  return `${w.y}-${String(w.m).padStart(2, '0')}-${String(w.d).padStart(2, '0')}`;
}

/** This month in Cairo, YYYY-MM. */
export function cairoThisMonth(): string {
  return cairoToday().slice(0, 7);
}

/** The first month PHAROS screened: its first check ran on 5 November 2026. A month before it was never
 *  watched, so a report or log for it would read as "screened, nothing found". */
export const PHAROS_START_MONTH = '2026-11';

/** Whether PHAROS was screening in a month ("2026-11" or a "2026-11-01" date). */
export function isScreenedMonth(month: string): boolean {
  return month.slice(0, 7) >= PHAROS_START_MONTH;
}

/** The UTC bounds of a Cairo calendar month ("2026-10"), as ISO strings: [from, to). */
export function cairoMonthRange(month: string): { from: string; to: string } {
  const m = /^(\d{4})-(\d{2})$/.exec(month);
  const y = m ? Number(m[1]) : new Date().getUTCFullYear();
  const mo = m ? Number(m[2]) : new Date().getUTCMonth() + 1;
  const ny = mo === 12 ? y + 1 : y;
  const nm = mo === 12 ? 1 : mo + 1;
  return { from: cairoMidnightUtc(y, mo, 1).toISOString(), to: cairoMidnightUtc(ny, nm, 1).toISOString() };
}

/** "October 2026" for "2026-10". */
export function formatYearMonth(month: string): string {
  return formatMonth(`${month}-01`);
}

const numberFmt = new Intl.NumberFormat('en-GB');
export function formatNumber(n: number | null | undefined): string {
  return n == null ? '—' : numberFmt.format(n);
}
