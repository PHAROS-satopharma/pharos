import { describe, expect, it } from 'vitest';
import { withClockDecision, withSent, withWithdrawn } from './clock';
import {
  caseReportLabel,
  chunk,
  dueLine,
  mergePaperPages,
  mlmLabel,
  orderPapers,
  paperIssueIds,
  withPaperDecision,
  type PaperState,
  type PaperStates,
} from './papers';
import { withSignal } from './signalSteps';
import type { FindingSignal, FindingState, PaperPage } from './types';

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

describe("the five-day clock of the papers' notices", () => {
  const running: FindingState = { day_zero: '2026-11-03', due: '2026-11-08', days_left: 2, clock: 'running', sent: null, signal: null };
  const off: FindingState = { ...running, clock: 'off' };

  it("asks finding_state for each paper's notice once, and never for a paper without one", () => {
    const states: PaperStates = {
      a: state({ issue_id: 'n1' }),
      b: state({ issue_id: 'n2' }),
      c: state({ issue_id: 'n1' }),
      d: state({ issue_id: null, issue_status: null }),
    };
    expect(paperIssueIds(states)).toEqual(['n1', 'n2']);
    expect(paperIssueIds({})).toEqual([]);
  });

  it('puts the pages together: every state and every clock, a page not answered yet left out', () => {
    const one: PaperPage = { states: { a: state({ issue_id: 'n1' }) }, findings: { n1: running } };
    const two: PaperPage = { states: { b: state({ issue_id: 'n2' }) }, findings: { n2: off } };
    const all = mergePaperPages([one, undefined, two]);
    expect(Object.keys(all.states)).toEqual(['a', 'b']);
    expect(all.findings).toEqual({ n1: running, n2: off });
    expect(mergePaperPages([])).toEqual({ states: {}, findings: {} });
  });

  it('follows a decision, a report, a withdrawal and a signal step on the page that holds the notice', () => {
    const page: PaperPage = { states: { a: state({ issue_id: 'n1' }) }, findings: { n1: off } };
    const on = withClockDecision(page, 'n1', 'relevant', '2026-11-06');
    expect(on.findings.n1).toMatchObject({ clock: 'running', days_left: 2 });
    expect(on.states).toBe(page.states);
    const sent = { id: 'r1', on: '2026-11-06', reference: null, person: 'Sama Mosaad', note: null };
    const reported = withSent(on, 'n1', sent);
    expect(reported.findings.n1).toMatchObject({ clock: 'sent', sent });
    expect(withWithdrawn(reported, 'n1', '2026-11-06').findings.n1).toMatchObject({ clock: 'running', sent: null });
    const signal: FindingSignal = {
      id: 's1',
      ref: 'SIG-2026-001',
      title: 'Tendon rupture',
      stage: 'validation',
      priority: null,
      outcome: null,
      next_step: 'validated',
      next_due: '2026-11-20',
      overdue: false,
      owner: null,
      opened_at: '2026-11-06T09:00:00Z',
      opened_by: 'Sama Mosaad',
      steps: [],
    };
    expect(withSignal(on, 'n1', signal).findings.n1.signal).toEqual(signal);
    // a page without the notice is returned as it was
    expect(withClockDecision(page, 'n9', 'relevant', '2026-11-06')).toBe(page);
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
