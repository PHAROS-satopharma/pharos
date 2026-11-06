import { describe, expect, it } from 'vitest';
import {
  canSend,
  clockLine,
  daysUntil,
  dueLabel,
  earliestSentDay,
  isClockRefusal,
  issueIdsOf,
  runningClock,
  withClockDecision,
  withSent,
  withWithdrawn,
} from './clock';
import { cairoDayOf } from './range';
import type { FindingState, IngredientScreenData, Mention } from './types';

const mention = (document_id: string, issue_id: string | null): Mention => ({
  document_id,
  source_id: 'src',
  regulator_id: 'R',
  regulator_name: 'R',
  country_name: 'X',
  country_code: 'XX',
  title: document_id,
  lang: 'en',
  link: null,
  email_id: null,
  email_r2_key: null,
  date: '2026-11-03',
  published_date: '2026-11-03',
  first_seen_at: '2026-11-03T08:00:00Z',
  doc_type: 'dhpc',
  terms: [],
  by_class: false,
  relation: 'name',
  class_name: null,
  is_backfill: false,
  sections: null,
  issue_id,
  issue_status: issue_id ? 'relevant' : null,
  decision: null,
});

const running: FindingState = { day_zero: '2026-11-03', due: '2026-11-08', days_left: 2, clock: 'running', sent: null, signal: null };

const DATA: IngredientScreenData = {
  ingredient: { id: 'i', inn_en: 'levofloxacin', atc_code: 'J01MA12', active: true, classes: [], names: 1, name_languages: 1, class_words: 0, class_languages: 0 },
  from: '2026-11-01',
  to: '2026-11-07',
  regulators: [
    { id: 'A', name: 'A', country_name: 'A', country_code: 'XX', homepage: null, hers: true, runs: 1, ok: 1, failed: 0, unread_page: false, pages: [], sources: [], mentions: [mention('a1', 'n1'), mention('a2', 'n2'), mention('a3', null)] },
    { id: 'B', name: 'B', country_name: 'B', country_code: 'XX', homepage: null, hers: true, runs: 1, ok: 1, failed: 0, unread_page: false, pages: [], sources: [], mentions: [mention('b1', 'n1')] },
  ],
  label_changes: [mention('l1', 'n3')],
  literature: { papers: 0, by_name: 0, by_class: 0, pubmed: 0, pmc: 0, by_query: [], first: [] },
  findings: {
    n1: running,
    n2: { day_zero: '2026-10-29', due: '2026-11-03', days_left: -3, clock: 'late', sent: null, signal: null },
    n3: { day_zero: '2026-11-01', due: '2026-11-06', days_left: 0, clock: 'off', sent: null, signal: null },
  },
};

describe('issueIdsOf', () => {
  it('names each notice once, from every country and the label changes, never an unfiled mention', () => {
    expect(issueIdsOf(DATA)).toEqual(['n1', 'n2', 'n3']);
  });
});

describe('clockLine', () => {
  it('words the clock as she reads it', () => {
    expect(dueLabel('2026-11-11')).toBe('Wed 11 Nov');
    expect(clockLine(running)).toBe('Authority: due Sun 8 Nov, 2 days left');
    expect(clockLine({ ...running, days_left: 1 })).toBe('Authority: due Sun 8 Nov, 1 day left');
    expect(clockLine({ ...running, days_left: 0 })).toBe('Authority: due today, Sun 8 Nov');
    expect(clockLine(DATA.findings.n2)).toBe('Authority: late by 3 days (was due Tue 3 Nov)');
    expect(clockLine({ ...running, days_left: -1, clock: 'late' })).toBe('Authority: late by 1 day (was due Sun 8 Nov)');
    expect(
      clockLine({ ...running, clock: 'sent', sent: { id: 's', on: '2026-11-10', reference: 'EDA/2026/0042', person: 'Dr Sama', note: null } }),
    ).toBe('Sent to the authority 10 Nov 2026 · ref EDA/2026/0042');
    expect(clockLine({ ...running, clock: 'sent', sent: { id: 's', on: '2026-11-10', reference: null, person: 'Dr Sama', note: null } })).toBe(
      'Sent to the authority 10 Nov 2026',
    );
  });

  it('says nothing while the clock is off, and offers "Sent" only while it runs or is late', () => {
    expect(clockLine(DATA.findings.n3)).toBeNull();
    expect(clockLine(undefined)).toBeNull();
    expect(canSend(running)).toBe(true);
    expect(canSend(DATA.findings.n2)).toBe(true);
    expect(canSend(DATA.findings.n3)).toBe(false);
    expect(canSend({ ...running, clock: 'sent' })).toBe(false);
    expect(canSend(undefined)).toBe(false);
  });
});

describe('the clock on a Cairo day', () => {
  it('counts the days left to the due day, negative when late', () => {
    expect(daysUntil('2026-11-06', '2026-11-08')).toBe(2);
    expect(daysUntil('2026-11-08', '2026-11-08')).toBe(0);
    expect(daysUntil('2026-11-10', '2026-11-08')).toBe(-2);
    expect(daysUntil('2026-12-31', '2027-01-02')).toBe(2);
  });

  it('turns late at midnight in Cairo, not in UTC', () => {
    // due Sunday 8 Nov 2026; Cairo is UTC+2 in November
    const beforeMidnight = cairoDayOf(new Date('2026-11-08T21:59:00Z'));
    const afterMidnight = cairoDayOf(new Date('2026-11-08T22:00:00Z'));
    expect(runningClock(running, beforeMidnight)).toMatchObject({ clock: 'running', days_left: 0 });
    expect(runningClock(running, afterMidnight)).toMatchObject({ clock: 'late', days_left: -1 });
  });

  it('follows summer time (UTC+3)', () => {
    const f: FindingState = { ...running, day_zero: '2026-07-10', due: '2026-07-15' };
    expect(runningClock(f, cairoDayOf(new Date('2026-07-15T20:59:00Z')))).toMatchObject({ clock: 'running', days_left: 0 });
    expect(runningClock(f, cairoDayOf(new Date('2026-07-15T21:00:00Z')))).toMatchObject({ clock: 'late', days_left: -1 });
  });
});

describe('the screen after a change', () => {
  const sent = { id: 's1', on: '2026-11-06', reference: 'EDA/2026/0042', person: 'Dr Sama', note: null };

  it('stops the clock of the notice once it is sent, and leaves the others', () => {
    const after = withSent(DATA, 'n1', sent);
    expect(after.findings.n1).toEqual({ ...running, clock: 'sent', sent });
    expect(after.findings.n2).toBe(DATA.findings.n2);
    expect(DATA.findings.n1.clock).toBe('running');
  });

  it("switches the clock off on Doesn't concern us and starts it on Concerns us, from the same due day", () => {
    const off = withClockDecision(DATA, 'n1', 'not_relevant', '2026-11-06');
    expect(off.findings.n1).toMatchObject({ clock: 'off', sent: null, due: '2026-11-08' });
    const on = withClockDecision(DATA, 'n3', 'relevant', '2026-11-06');
    expect(on.findings.n3).toMatchObject({ clock: 'running', days_left: 0, due: '2026-11-06' });
    const late = withClockDecision(DATA, 'n3', 'relevant', '2026-11-09');
    expect(late.findings.n3).toMatchObject({ clock: 'late', days_left: -3 });
  });

  it('never forgets a report sent to the authority: off keeps it, Concerns us again finds the notice sent', () => {
    const sentData = withSent(DATA, 'n1', sent);
    const off = withClockDecision(sentData, 'n1', 'not_relevant', '2026-11-06');
    expect(off.findings.n1).toMatchObject({ clock: 'off', sent });
    const again = withClockDecision(off, 'n1', 'relevant', '2026-11-09');
    expect(again.findings.n1).toMatchObject({ clock: 'sent', sent, due: '2026-11-08' });
  });

  it('dates a report no earlier than the day PHAROS first showed the notice, and no later than today', () => {
    expect(earliestSentDay(running)).toBe('2026-11-03');
    expect(earliestSentDay(undefined)).toBeUndefined();
  });

  it('starts the clock again when a wrong report is withdrawn', () => {
    const sentData = withSent(DATA, 'n1', sent);
    expect(withWithdrawn(sentData, 'n1', '2026-11-06').findings.n1).toMatchObject({ clock: 'running', days_left: 2, sent: null });
    expect(withWithdrawn(sentData, 'n1', '2026-11-12').findings.n1).toMatchObject({ clock: 'late', days_left: -4, sent: null });
  });

  it('leaves the screen alone for a notice it does not know', () => {
    expect(withSent(DATA, 'nope', sent)).toBe(DATA);
    expect(withClockDecision(DATA, 'nope', 'relevant', '2026-11-06')).toBe(DATA);
  });
});

describe('isClockRefusal', () => {
  it('knows the database refusing a report (PH409: no concern, or sent already)', () => {
    expect(isClockRefusal({ code: 'PH409', message: 'NO_CONCERN: …' })).toBe(true);
    expect(isClockRefusal({ message: 'ALREADY_SENT: this decision was already reported' })).toBe(true);
    expect(isClockRefusal({ code: '42501', message: 'permission denied' })).toBe(false);
    expect(isClockRefusal(null)).toBe(false);
  });
});
