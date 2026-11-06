import { describe, expect, it } from 'vitest';
import { auditLine, flaggedLine, type MatchAuditRow } from './matchAudit';

const row = (over: Partial<MatchAuditRow> = {}): MatchAuditRow => ({
  checked_at: '2026-11-08T00:53:00Z',
  notices_named: 41,
  unlinked_found: 0,
  linked_now: 0,
  left_over: [],
  flagged_names: [],
  unchecked_names: 0,
  ...over,
});

describe('auditLine', () => {
  it('says all linked when nothing was missed', () => {
    expect(auditLine(row(), '8 Nov')).toBe('Audit 8 Nov: 41 notices name it, all linked');
  });
  it('counts what it linked and what is left', () => {
    expect(auditLine(row({ unlinked_found: 7, linked_now: 6 }), '8 Nov')).toBe(
      'Audit 8 Nov: 41 notices name it; 7 were not linked, 6 linked now, 1 still to look at',
    );
    expect(auditLine(row({ notices_named: 1, unlinked_found: 1, linked_now: 1 }), '8 Nov')).toBe(
      'Audit 8 Nov: 1 notice names it; 1 was not linked, 1 linked now',
    );
  });
});

describe('flaggedLine', () => {
  it('names each flagged name and what could not be checked', () => {
    expect(flaggedLine(row())).toBeNull();
    expect(
      flaggedLine(
        row({ flagged_names: [{ term_id: 'n1', term: 'Ofloxacin', why: 'RxNorm: ofloxacin' }], unchecked_names: 2 }),
      ),
    ).toBe('Belongs to another substance: “Ofloxacin” (RxNorm: ofloxacin), 2 names could not be checked');
  });
});
