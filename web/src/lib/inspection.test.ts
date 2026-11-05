import { describe, expect, it } from 'vitest';
import { auditChange, daysBetween, hoursBetween, median } from './inspection';

describe('daysBetween', () => {
  it('lists every day, across a month end and a leap day', () => {
    expect(daysBetween('2028-02-27', '2028-03-01')).toEqual(['2028-02-27', '2028-02-28', '2028-02-29', '2028-03-01']);
    expect(daysBetween('2026-11-05', '2026-11-05')).toEqual(['2026-11-05']);
  });
});

describe('time to the first decision', () => {
  it('counts hours to one decimal, and nothing without a decision', () => {
    expect(hoursBetween('2026-11-05T06:00:00Z', '2026-11-05T09:30:00Z')).toBe(3.5);
    expect(hoursBetween('2026-11-05T06:00:00Z', null)).toBeNull();
  });
  it('takes the middle value, or the mean of the two middle ones', () => {
    expect(median([5, 1, 3])).toBe(3);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNull();
  });
});

describe('auditChange', () => {
  it('names the fields an update changed, never updated_at', () => {
    expect(auditChange('UPDATE', { a: 1, b: 'x', updated_at: 1 }, { a: 2, b: 'x', updated_at: 2 })).toBe('Changed a');
    expect(auditChange('INSERT', null, { a: 1 })).toBe('Created');
    expect(auditChange('DELETE', { a: 1 }, null)).toBe('Removed');
  });
});
