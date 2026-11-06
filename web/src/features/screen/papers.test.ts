import { describe, expect, it } from 'vitest';
import {
  caseReportLabel,
  chunk,
  dueLine,
  mlmLabel,
  orderPapers,
  withPaperDecision,
  type PaperState,
  type PaperStates,
} from './papers';

const state = (over: Partial<PaperState> = {}): PaperState => ({
  issue_id: 'n1',
  issue_status: 'new',
  decision: null,
  case_report: null,
  day_zero: '2026-11-05',
  due_serious: '2026-11-20',
  due_nonserious: '2027-02-03',
  ...over,
});

describe('a possible case report', () => {
  it('says why it looks like one', () => {
    expect(caseReportLabel({ reason: 'pubtype' })).toBe('PubMed lists it as a case report');
    expect(caseReportLabel({ reason: 'title' })).toBe('Its title says so');
  });

  it('shows day zero and the 15- and 90-day dates, the year once unless it changes', () => {
    expect(dueLine(state())).toBe('day zero 5 Nov 2026 · 15 days: 20 Nov · 90 days: 3 Feb 2027');
    expect(dueLine(state({ day_zero: '2026-03-01', due_serious: '2026-03-16', due_nonserious: '2026-05-30' }))).toBe(
      'day zero 1 Mar 2026 · 15 days: 16 Mar · 90 days: 30 May',
    );
  });
});

describe('the papers on screen', () => {
  const papers = [{ document_id: 'a' }, { document_id: 'b' }, { document_id: 'c' }, { document_id: 'd' }];
  const states: PaperStates = {
    a: state(),
    b: state({ case_report: { reason: 'title' } }),
    d: state({ case_report: { reason: 'pubtype' } }),
  };

  it('lists the possible case reports first and keeps the order otherwise', () => {
    expect(orderPapers(papers, states).map((p) => p.document_id)).toEqual(['b', 'd', 'a', 'c']);
    // a paper whose state has not arrived yet stays where it was
    expect(orderPapers(papers, {}).map((p) => p.document_id)).toEqual(['a', 'b', 'c', 'd']);
  });

  it('shows a decision at once on every paper filed under the same notice', () => {
    const shared: PaperStates = { a: state({ issue_id: 'n1' }), b: state({ issue_id: 'n1' }), c: state({ issue_id: 'n2' }) };
    const d = { to_status: 'relevant' as const, person: 'Sama Hassan', at: '2026-11-06T09:00:00Z', comment: null };
    const after = withPaperDecision(shared, 'n1', d);
    expect(after.a.issue_status).toBe('relevant');
    expect(after.b.decision).toEqual(d);
    expect(after.c).toBe(shared.c);
    expect(shared.a.issue_status).toBe('new'); // never changed in place
  });

  it('asks the database 50 papers at a time', () => {
    expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    expect(chunk([], 50)).toEqual([]);
  });
});

describe("EMA's literature monitoring", () => {
  it('says in plain words whether EMA reads the literature for this ingredient', () => {
    expect(mlmLabel(true)?.label).toBe('Monitored by EMA (MLM)');
    expect(mlmLabel(false)?.label).toBe('Not monitored by EMA');
    expect(mlmLabel(false)?.explain).toMatch(/ours to report/);
    expect(mlmLabel(undefined)).toBeNull();
  });
});
