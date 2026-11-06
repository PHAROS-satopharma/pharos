import { describe, expect, it } from 'vitest';
import { chainOf, isStaleSignal, needsDue, nextSteps, stepDue, withSignal } from './signalSteps';
import type { FindingSignal, FindingState, IngredientScreenData } from './types';

const signal: FindingSignal = {
  id: 'sig-1',
  ref: 'SIG-2026-001',
  title: 'Rote-Hand-Brief Levofloxacin',
  stage: 'validation',
  priority: null,
  outcome: null,
  next_step: 'validated',
  next_due: '2026-12-06',
  overdue: false,
  owner: null,
  opened_at: '2026-11-06T08:00:00Z',
  opened_by: 'Dr Sama',
  steps: [
    {
      step: 'opened',
      from_stage: null,
      to_stage: 'validation',
      priority: null,
      outcome: null,
      person: 'Dr Sama',
      at: '2026-11-06T08:00:00Z',
      comment: null,
    },
  ],
};

const finding: FindingState = { day_zero: '2026-11-06', due: '2026-11-11', days_left: 5, clock: 'running', sent: null, signal };

const DATA: IngredientScreenData = {
  ingredient: { id: 'i', inn_en: 'levofloxacin', atc_code: 'J01MA12', active: true, classes: [], names: 1, name_languages: 1, class_words: 0, class_languages: 0 },
  from: '2026-11-01',
  to: '2026-11-07',
  regulators: [],
  label_changes: [],
  literature: {
    papers: 0,
    by_name: 0,
    by_class: 0,
    pubmed: 0,
    pmc: 0,
    europepmc: 0,
    preprints: 0,
    by_query: [],
    first: [],
  },
  findings: { n1: finding, n2: { ...finding, signal: null } },
};

describe('the next step per stage', () => {
  it('offers her two answers in validation, one step after', () => {
    expect(nextSteps('validation').map((s) => s.step)).toEqual(['validated', 'not_validated']);
    expect(nextSteps('assessment').map((s) => s.step)).toEqual(['assessed']);
    expect(nextSteps('action').map((s) => s.step)).toEqual(['action_done']);
    expect(nextSteps('closed').map((s) => s.step)).toEqual(['reopened']);
  });

  it('asks for a priority when it is a signal, an outcome when assessed, and words every time', () => {
    const [yes, no] = nextSteps('validation');
    expect(yes).toMatchObject({ label: 'It is a signal', needsPriority: true, needsOutcome: false });
    expect(no).toMatchObject({ label: 'Not a signal', needsPriority: false, needsOutcome: false });
    expect(nextSteps('assessment')[0]).toMatchObject({ label: 'Record the assessment', needsOutcome: true });
    expect(nextSteps('action')[0].label).toBe('Action done');
    expect(nextSteps('closed')[0].label).toBe('Reopen');
  });

  it('needs a due date only for an outcome that opens an action', () => {
    expect(needsDue('label_update')).toBe(true);
    expect(needsDue('rmp_update')).toBe(true);
    expect(needsDue('dhpc')).toBe(true);
    expect(needsDue('psur_input')).toBe(true);
    expect(needsDue('refuted')).toBe(false);
    expect(needsDue('monitor')).toBe(false);
    expect(needsDue('no_action')).toBe(false);
    expect(needsDue(null)).toBe(false);
  });
});

describe('the chain', () => {
  it('lights the current stage and marks the ones before it done', () => {
    expect(chainOf('validation').map((c) => c.state)).toEqual(['current', 'todo', 'todo', 'todo']);
    expect(chainOf('assessment').map((c) => c.state)).toEqual(['done', 'current', 'todo', 'todo']);
    expect(chainOf('action').map((c) => c.state)).toEqual(['done', 'done', 'current', 'todo']);
    expect(chainOf('closed').map((c) => c.state)).toEqual(['done', 'done', 'done', 'current']);
    expect(chainOf('validation').map((c) => c.label)).toEqual(['Validate', 'Assess', 'Action', 'Closed']);
  });
});

describe('the next due day', () => {
  it('names the step and the day, and says late', () => {
    expect(stepDue(signal)).toEqual({ text: 'Validate by Sun 6 Dec', late: false });
    expect(stepDue({ ...signal, overdue: true, next_due: '2026-11-03' })).toEqual({ text: 'Validate by Tue 3 Nov', late: true });
    expect(stepDue({ ...signal, stage: 'assessment', next_due: '2026-12-20' })).toEqual({ text: 'Assess by Sun 20 Dec', late: false });
    expect(stepDue({ ...signal, stage: 'action', next_due: '2027-01-15' })).toEqual({ text: 'Action by Fri 15 Jan', late: false });
  });

  it('says nothing for a closed signal or one with no due day', () => {
    expect(stepDue({ ...signal, stage: 'closed', next_due: null })).toBeNull();
    expect(stepDue({ ...signal, next_due: null })).toBeNull();
  });
});

describe('the database refused the step', () => {
  it('knows a stale stage from its code or its message', () => {
    expect(isStaleSignal({ code: 'PH409', message: 'STALE_SIGNAL: someone else moved this signal' })).toBe(true);
    expect(isStaleSignal({ message: 'STALE_SIGNAL: someone else moved this signal a moment ago' })).toBe(true);
    expect(isStaleSignal({ code: '22023', message: 'This step needs a comment for the record.' })).toBe(false);
    expect(isStaleSignal(null)).toBe(false);
    expect(isStaleSignal(undefined)).toBe(false);
  });
});

describe('the screen after a step', () => {
  it('replaces the signal of the notice and leaves the clock and the other notices alone', () => {
    const moved: FindingSignal = { ...signal, stage: 'assessment', priority: 'high', next_step: 'assessed', next_due: '2026-12-06' };
    const after = withSignal(DATA, 'n1', moved);
    expect(after.findings.n1.signal).toEqual(moved);
    expect(after.findings.n1.clock).toBe('running');
    expect(after.findings.n2).toBe(DATA.findings.n2);
    expect(DATA.findings.n1.signal).toEqual(signal);
  });

  it('can take the signal away, and ignores a notice the screen does not know', () => {
    expect(withSignal(DATA, 'n1', null).findings.n1.signal).toBeNull();
    expect(withSignal(DATA, 'unknown', signal)).toBe(DATA);
  });
});
