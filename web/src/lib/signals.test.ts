import { describe, expect, it } from 'vitest';
import { daysUntil, dueWords, stepsFor } from './signals';

describe('dueWords', () => {
  it('counts Cairo calendar days, across a month end', () => {
    expect(daysUntil('2026-12-02', '2026-11-29')).toBe(3);
    expect(dueWords('2026-12-02', '2026-11-29')).toBe('Due in 3 days');
  });
  it('says today, one day and overdue plainly', () => {
    expect(dueWords('2026-11-05', '2026-11-05')).toBe('Due today');
    expect(dueWords('2026-11-06', '2026-11-05')).toBe('Due in 1 day');
    expect(dueWords('2026-11-04', '2026-11-05')).toBe('1 day overdue');
    expect(dueWords('2026-10-26', '2026-11-05')).toBe('10 days overdue');
  });
  it('has no due date when none is set', () => {
    expect(dueWords(null, '2026-11-05')).toBe('No due date');
  });
});

describe('stepsFor', () => {
  it('offers validation only to a signal in validation, and reopening only to a closed one', () => {
    expect(stepsFor('validation')).toContain('validated');
    expect(stepsFor('assessment')).not.toContain('validated');
    expect(stepsFor('closed')).toEqual(['reopened', 'note']);
  });
});
