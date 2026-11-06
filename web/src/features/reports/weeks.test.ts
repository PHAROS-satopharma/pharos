import { describe, expect, it } from 'vitest';
import {
  FIRST_WEEK,
  dailyFileName,
  dayLabel,
  lastCompleteWeek,
  newestWeekFirst,
  weekDays,
  weekLabel,
  weekOptions,
  weeklyFileName,
} from './weeks';

describe('weekLabel', () => {
  it('names the week as the report does', () => {
    expect(weekLabel('2026-11-01')).toBe('Sun 1 Nov – Sat 7 Nov 2026');
    expect(weekLabel('2026-10-25')).toBe('Sun 25 Oct – Sat 31 Oct 2026');
  });
  it('writes both years only when the week crosses into a new one', () => {
    expect(weekLabel('2026-12-27')).toBe('Sun 27 Dec 2026 – Sat 2 Jan 2027');
  });
});

describe('weekDays', () => {
  it('runs Sunday to Saturday, both included', () => {
    expect(weekDays('2026-11-01')).toEqual({ from: '2026-11-01', to: '2026-11-07' });
    expect(weekDays('2026-12-27')).toEqual({ from: '2026-12-27', to: '2027-01-02' });
  });
});

describe('lastCompleteWeek', () => {
  it('is the week that ended last Saturday', () => {
    expect(lastCompleteWeek('2026-11-08')).toBe('2026-11-01');
    expect(lastCompleteWeek('2026-11-14')).toBe('2026-11-01');
    expect(lastCompleteWeek('2026-11-15')).toBe('2026-11-08');
  });
  it('is never before the first week PHAROS screened', () => {
    expect(lastCompleteWeek('2026-11-06')).toBe(FIRST_WEEK);
  });
});

describe('weekOptions', () => {
  it('offers this week first, back to the first week', () => {
    expect(weekOptions('2026-11-18').map((o) => o.value)).toEqual(['2026-11-15', '2026-11-08', '2026-11-01']);
    expect(weekOptions('2026-11-18')[0].label).toBe('Sun 15 Nov – Sat 21 Nov 2026 (this week, so far)');
    expect(weekOptions('2026-11-18')[1].label).toBe('Sun 8 Nov – Sat 14 Nov 2026');
  });
  it('offers only the first week while it is still running', () => {
    expect(weekOptions('2026-11-06').map((o) => o.value)).toEqual(['2026-11-01']);
  });
});

describe('weeklyFileName and newestWeekFirst', () => {
  it('saves under the name the report is archived with', () => {
    expect(weeklyFileName('2026-11-01', 'pdf')).toBe('PHAROS-weekly-2026-11-01.pdf');
    expect(weeklyFileName('2026-11-01', 'xlsx')).toBe('PHAROS-weekly-2026-11-01.xlsx');
  });
  it('lists the newest week first', () => {
    const rows = [{ week_start: '2026-11-01' }, { week_start: '2026-11-15' }, { week_start: '2026-11-08' }];
    expect(newestWeekFirst(rows).map((r) => r.week_start)).toEqual(['2026-11-15', '2026-11-08', '2026-11-01']);
  });
});

describe('the daily report', () => {
  it('names the day as the report does', () => {
    expect(dayLabel('2026-11-05')).toBe('Thu 5 Nov 2026');
    expect(dayLabel('2026-11-01')).toBe('Sun 1 Nov 2026');
    expect(dayLabel('2027-01-02')).toBe('Sat 2 Jan 2027');
  });
  it('saves its files under the day', () => {
    expect(dailyFileName('2026-11-05', 'pdf')).toBe('PHAROS-daily-2026-11-05.pdf');
    expect(dailyFileName('2026-11-05T00:00:00', 'xlsx')).toBe('PHAROS-daily-2026-11-05.xlsx');
  });
});
