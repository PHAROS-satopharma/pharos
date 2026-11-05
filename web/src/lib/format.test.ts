import { describe, expect, it } from 'vitest';
import { PHAROS_START_MONTH, formatPublishedDay, isScreenedMonth } from './format';

describe('isScreenedMonth', () => {
  it('starts at November 2026, the month of the first check', () => {
    expect(PHAROS_START_MONTH).toBe('2026-11');
    expect(isScreenedMonth('2026-11')).toBe(true);
    expect(isScreenedMonth('2026-12-01')).toBe(true);
    expect(isScreenedMonth('2027-01')).toBe(true);
  });

  it('hides the months PHAROS never watched', () => {
    expect(isScreenedMonth('2026-10')).toBe(false);
    expect(isScreenedMonth('2026-10-01')).toBe(false);
    expect(isScreenedMonth('2025-12-01')).toBe(false);
  });
});

describe('formatPublishedDay', () => {
  it('shows the day the regulator printed, with no invented time', () => {
    // Stored at UTC midnight; in Cairo summer time that instant is 03:00, which no regulator printed.
    expect(formatPublishedDay('2026-10-08T00:00:00+00:00')).toBe('8 Oct 2026');
    expect(formatPublishedDay('2026-12-31T00:00:00Z')).toBe('31 Dec 2026');
  });

  it('shows a dash when nothing has been published yet', () => {
    expect(formatPublishedDay(null)).toBe('—');
    expect(formatPublishedDay(undefined)).toBe('—');
  });
});
