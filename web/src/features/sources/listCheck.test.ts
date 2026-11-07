import { describe, expect, it } from 'vitest';
import { latestBySource, listLine, type ListCheckRow } from './listCheck';

function row(over: Partial<ListCheckRow> = {}): ListCheckRow {
  return {
    source_id: 'mhra-alerts',
    checked_at: '2026-11-08T01:30:00Z',
    listed: 1465,
    stored: 1465,
    older: 0,
    missing: 0,
    filtered: 0,
    missing_items: [],
    complete: true,
    error: null,
    ...over,
  };
}

describe('the list-check line of a source', () => {
  it('is absent before the first check', () => {
    expect(listLine(undefined)).toBeNull();
  });

  it('says every listed notice is stored, and needs no look', () => {
    expect(listLine(row())).toEqual({
      text: 'Whole list checked 8 Nov 2026: all 1,465 notices listed are stored.',
      needsLook: false,
    });
  });

  it('names the newest notice not stored, and what is older or filtered', () => {
    const r = row({
      listed: 120,
      stored: 116,
      older: 2,
      missing: 2,
      filtered: 4,
      missing_items: [{ external_id: 'a', title: 'Recall: batch 7', url: 'https://x.test/a', published: null }],
    });
    expect(listLine(r)).toEqual({
      text:
        'Whole list checked 8 Nov 2026: 2 of 120 notices listed are not stored, newest “Recall: batch 7” · ' +
        '2 older than the kept history · 4 left out by its filters.',
      needsLook: true,
    });
  });

  it('never calls a list read in part, or not at all, complete', () => {
    expect(listLine(row({ complete: false, error: '1 part(s) of the list could not be read' }))?.needsLook).toBe(true);
    expect(listLine(row({ listed: 0, stored: 0, complete: false, error: 'TimeoutError' }))).toEqual({
      text: 'Whole list checked 8 Nov 2026: not read (TimeoutError).',
      needsLook: true,
    });
  });

  it('keeps the latest row of each source', () => {
    const m = latestBySource([row({ listed: 2 }), row({ listed: 1 }), row({ source_id: 'b', listed: 3 })]);
    expect([m.get('mhra-alerts')?.listed, m.get('b')?.listed]).toEqual([2, 3]);
  });
});
