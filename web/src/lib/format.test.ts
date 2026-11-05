import { describe, expect, it } from 'vitest';
import { PHAROS_START_MONTH, isScreenedMonth } from './format';

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
