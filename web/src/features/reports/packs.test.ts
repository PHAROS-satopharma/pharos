import { describe, expect, it } from 'vitest';
import {
  daysLabel,
  daysProblem,
  lastTwelveMonths,
  newestFirst,
  packFileName,
  packLabel,
  psurDays,
  statusText,
  stillWaiting,
} from './packs';

const TODAY = '2026-11-06';

describe('the days of a pack, unless she changes them', () => {
  it('an inspection pack covers the last 12 months', () => {
    expect(lastTwelveMonths(TODAY)).toEqual({ from: '2025-11-07', to: '2026-11-06' });
    expect(lastTwelveMonths('2028-02-29')).toEqual({ from: '2027-03-01', to: '2028-02-29' });
  });
  it('a PSUR pack starts at the EURD interval and stops today (lornoxicam: 7 years to 1 Dec 2031)', () => {
    expect(psurDays([{ dlp: '2031-12-01', frequency: '7 years' }], TODAY)).toEqual({
      from: '2024-12-02',
      to: '2026-11-06',
      fromEurd: true,
    });
  });
  it('an interval already ended is the interval itself', () => {
    expect(psurDays([{ dlp: '2026-06-30', frequency: '6 months' }], TODAY)).toEqual({
      from: '2025-12-31',
      to: '2026-06-30',
      fromEurd: true,
    });
  });
  it('never more than five years', () => {
    expect(psurDays([{ dlp: '2026-10-01', frequency: '10 years' }], TODAY)).toEqual({
      from: '2021-10-02',
      to: '2026-10-01',
      fromEurd: true,
    });
  });
  it('the first row with an interval; without one, or one not started yet, the last 12 months', () => {
    expect(
      psurDays(
        [
          { dlp: null, frequency: '3 years' },
          { dlp: '2027-03-01', frequency: '3 years' },
        ],
        TODAY,
      ),
    ).toEqual({ from: '2024-03-02', to: TODAY, fromEurd: true });
    expect(psurDays([], TODAY)).toEqual({ from: '2025-11-07', to: TODAY, fromEurd: false });
    expect(psurDays([{ dlp: '2031-12-01', frequency: '6 months' }], TODAY)).toEqual({
      from: '2025-11-07',
      to: TODAY,
      fromEurd: false,
    });
  });
});

describe('days the database refuses are refused here first', () => {
  it('in her words', () => {
    expect(daysProblem('2025-01-01', '2026-11-06', TODAY)).toBeNull();
    expect(daysProblem('2026-02-01', '2026-01-01', TODAY)).toBe('The last day is before the first.');
    expect(daysProblem('2026-11-07', '2026-12-01', TODAY)).toBe('The first day is in the future.');
    expect(daysProblem('2020-01-01', '2025-01-01', TODAY)).toBeNull();
    expect(daysProblem('2020-01-01', '2025-01-02', TODAY)).toBe('A pack covers at most five years.');
    expect(daysProblem('', '2025-01-02', TODAY)).toBe('Choose the first and the last day.');
  });
});

describe('a request in words', () => {
  const psur = { kind: 'psur' as const, from_day: '2024-12-02', to_day: '2026-11-06' };
  const insp = { kind: 'inspection' as const, from_day: '2025-11-07', to_day: '2026-11-06' };
  it('is named as the pack and its Telegram message name it', () => {
    expect(daysLabel('2024-12-02', '2026-11-06')).toBe('2 Dec 2024 – 6 Nov 2026');
    expect(packLabel(psur, 'levofloxacin')).toBe('PSUR pack, levofloxacin, 2 Dec 2024 – 6 Nov 2026');
    expect(packLabel(insp, 'levofloxacin')).toBe('Inspection pack, 7 Nov 2025 – 6 Nov 2026');
  });
  it('saves its files under the names the collector archived them', () => {
    expect(packFileName(psur, 'levofloxacin', 'pdf')).toBe('PHAROS-PSUR-levofloxacin-2024-12-02-to-2026-11-06.pdf');
    expect(packFileName(psur, 'iron (III) sucrose', 'xlsx')).toBe(
      'PHAROS-PSUR-iron-III-sucrose-2024-12-02-to-2026-11-06.xlsx',
    );
    expect(packFileName(insp, null, 'xlsx')).toBe('PHAROS-inspection-2025-11-07-to-2026-11-06.xlsx');
  });
  it('says where it stands', () => {
    expect(statusText({ status: 'queued', error: null, attempts: 0 })).toBe(
      'Waiting for the next collection run (within four hours)',
    );
    expect(
      statusText({
        status: 'queued',
        error: 'Took longer than 15 minutes; the next collection run goes on with it.',
        attempts: 1,
      }),
    ).toBe('Waiting: Took longer than 15 minutes; the next collection run goes on with it.');
    expect(statusText({ status: 'building', error: null, attempts: 1 })).toBe('Being made now');
    expect(statusText({ status: 'failed', error: 'RuntimeError: timeout', attempts: 1 })).toBe(
      'Not made: RuntimeError: timeout',
    );
  });
  it('lists the newest first and is read again while one waits', () => {
    const rows = [
      { id: 'a', requested_at: '2026-11-06T08:00:00Z', status: 'done' as const },
      { id: 'b', requested_at: '2026-11-06T09:00:00Z', status: 'queued' as const },
    ];
    expect(newestFirst(rows).map((r) => r.id)).toEqual(['b', 'a']);
    expect(stillWaiting(rows)).toBe(true);
    expect(stillWaiting([rows[0]])).toBe(false);
  });
});
