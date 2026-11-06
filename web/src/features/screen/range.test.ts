import { describe, expect, it } from 'vitest';
import {
  MAX_DAYS,
  addDays,
  cairoDayOf,
  dayCount,
  presetDays,
  presetOf,
  rangeError,
  rangeFromSearch,
  rangeLabel,
  weekStartOf,
} from './range';

describe('cairoDayOf', () => {
  it('turns over at midnight in Cairo, not in UTC (winter, UTC+2)', () => {
    expect(cairoDayOf(new Date('2026-11-07T21:59:00Z'))).toBe('2026-11-07');
    expect(cairoDayOf(new Date('2026-11-07T22:00:00Z'))).toBe('2026-11-08');
  });

  it('follows summer time (UTC+3)', () => {
    expect(cairoDayOf(new Date('2026-07-15T20:59:00Z'))).toBe('2026-07-15');
    expect(cairoDayOf(new Date('2026-07-15T21:00:00Z'))).toBe('2026-07-16');
  });
});

describe('days', () => {
  it('counts both ends and crosses months and years', () => {
    expect(dayCount('2026-11-01', '2026-11-07')).toBe(7);
    expect(dayCount('2026-11-06', '2026-11-06')).toBe(1);
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
  });

  it('starts weeks on Sunday', () => {
    expect(weekStartOf('2026-11-06')).toBe('2026-11-01'); // a Friday
    expect(weekStartOf('2026-11-01')).toBe('2026-11-01'); // a Sunday
    expect(weekStartOf('2026-11-07')).toBe('2026-11-01'); // a Saturday
  });
});

describe('presetDays', () => {
  it('gives this week from Sunday to today, last week, and the last 30 days', () => {
    expect(presetDays('this-week', '2026-11-06')).toEqual({ from: '2026-11-01', to: '2026-11-06' });
    expect(presetDays('last-week', '2026-11-06')).toEqual({ from: '2026-10-25', to: '2026-10-31' });
    expect(presetDays('last-30', '2026-11-06')).toEqual({ from: '2026-10-08', to: '2026-11-06' });
  });

  it('is one day on a Sunday', () => {
    expect(presetDays('this-week', '2026-11-08')).toEqual({ from: '2026-11-08', to: '2026-11-08' });
  });
});

describe('rangeError', () => {
  it('accepts up to 366 days and refuses more, as the database does', () => {
    expect(MAX_DAYS).toBe(366);
    expect(rangeError('2025-11-07', '2026-11-07')).toBeNull();
    expect(rangeError('2025-11-06', '2026-11-07')).toBe('Choose at most 366 days.');
  });

  it('refuses a missing or impossible day, and days that end before they start', () => {
    expect(rangeError('', '2026-11-07')).toBe('Give both days.');
    expect(rangeError('2026-02-30', '2026-03-01')).toBe('Give both days.');
    expect(rangeError('2026-11-07', '2026-11-01')).toBe('The last day is before the first.');
  });
});

describe('rangeFromSearch', () => {
  const today = '2026-11-06';

  it('is this week when the address names no days', () => {
    expect(rangeFromSearch(new URLSearchParams(''), today)).toEqual({
      from: '2026-11-01',
      to: '2026-11-06',
      preset: 'this-week',
    });
  });

  it('keeps the days of the address, and recognises a preset from its days', () => {
    expect(rangeFromSearch(new URLSearchParams('from=2026-09-01&to=2026-09-30'), today)).toEqual({
      from: '2026-09-01',
      to: '2026-09-30',
      preset: 'custom',
    });
    expect(rangeFromSearch(new URLSearchParams('from=2026-10-25&to=2026-10-31'), today).preset).toBe('last-week');
    expect(presetOf('2026-10-08', '2026-11-06', today)).toBe('last-30');
  });

  it('falls back to this week for days the database would refuse', () => {
    expect(rangeFromSearch(new URLSearchParams('from=2026-11-07&to=2026-11-01'), today).preset).toBe('this-week');
    expect(rangeFromSearch(new URLSearchParams('from=2024-01-01&to=2026-11-01'), today).preset).toBe('this-week');
  });
});

describe('rangeLabel', () => {
  it('names the days in plain words', () => {
    expect(rangeLabel('2026-11-01', '2026-11-06')).toBe('1 Nov 2026 – 6 Nov 2026');
    expect(rangeLabel('2026-11-06', '2026-11-06')).toBe('6 Nov 2026');
  });
});
