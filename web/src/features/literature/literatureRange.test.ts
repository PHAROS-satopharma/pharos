import { describe, expect, it } from 'vitest';
import { isDay, literatureSearchKey, rangeProblem } from './literatureRange';

describe('the date range for live NCBI counts', () => {
  it('takes real calendar days only', () => {
    expect(isDay('2026-10-01')).toBe(true);
    expect(isDay('2024-02-29')).toBe(true);
    expect(isDay('2026-02-29')).toBe(false);
    expect(isDay('2026-13-01')).toBe(false);
    expect(isDay('1 Oct 2026')).toBe(false);
    expect(isDay('')).toBe(false);
    expect(isDay(null)).toBe(false);
  });

  it('says what is wrong with a range, and nothing when NCBI can be asked', () => {
    expect(rangeProblem('2026-10-01', '2026-10-31')).toBeNull();
    expect(rangeProblem('2026-10-01', '2026-10-01')).toBeNull();
    expect(rangeProblem('2026-10-31', '2026-10-01')).toBe('The first date is after the last one.');
    expect(rangeProblem('2026-10-01', undefined)).toBe('Give both dates.');
    expect(rangeProblem('1700-01-01', '2026-10-01')).toBe('The first date is too early.');
  });

  it('keeps one answer per ingredient and range', () => {
    expect(literatureSearchKey('a', '2026-10-01', '2026-10-31')).toEqual(['literature-search', 'a', '2026-10-01', '2026-10-31']);
    expect(literatureSearchKey('a', '2026-10-01', '2026-10-31')).not.toEqual(literatureSearchKey('b', '2026-10-01', '2026-10-31'));
  });
});
