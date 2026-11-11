import { describe, expect, it } from 'vitest';
import {
  type Capa,
  type Deadline,
  type DeviationProposal,
  auditSteps,
  capaCounts,
  capaDueText,
  capaSourceText,
  capaSteps,
  capasOf,
  dayText,
  daysBetween,
  deadlineText,
  deviationSteps,
  filterCapas,
  historyWords,
  isStale,
  nextDeadline,
  proposalDueText,
  shortDay,
  sortCapas,
  waitingProposals,
} from './quality';

function capa(over: Partial<Capa>): Capa {
  return {
    id: 'c',
    ref: 'CAPA-001/2026',
    year: 2026,
    serial: 1,
    source: 'deviation',
    deviation_id: 'd1',
    deviation_ref: 'D001/2026',
    observation_id: null,
    observation_number: null,
    audit_id: null,
    audit_title: null,
    audit_kind: null,
    corrective_action: 'Fix',
    preventive_action: null,
    owner_id: 'p1',
    owner_other: null,
    owner_name: 'Dr Sama Mosaad',
    due_on: '2026-11-19',
    status: 'in_progress',
    evidence: null,
    done_on: null,
    verified_by: null,
    verified_at: null,
    created_by: 'Dr Sama Mosaad',
    created_at: '2026-11-09T08:00:00Z',
    due: { due: '2026-11-19', done_on: null, days_left: 3, state: 'running' },
    history: [],
    ...over,
  };
}

describe('days in Cairo words', () => {
  it('names the weekday, the day, the month and the year', () => {
    expect(dayText('2026-11-19')).toBe('Thu 19 Nov 2026');
    expect(shortDay('2026-11-19')).toBe('Thu 19 Nov');
    expect(dayText(null)).toBe('—');
  });
  it('counts calendar days across a month and a year', () => {
    expect(daysBetween('2026-11-28', '2026-12-02')).toBe(4);
    expect(daysBetween('2026-12-31', '2027-01-01')).toBe(1);
    expect(daysBetween('2026-11-19', '2026-11-17')).toBe(-2);
  });
});

describe('the audit deadlines (PV-SOP-022, from the day the report was received)', () => {
  const d = (over: Partial<Deadline>): Deadline => ({
    key: 'draft',
    due: '2026-11-19',
    done_on: null,
    days_left: 3,
    state: 'running',
    ...over,
  });
  it('says the day and the days left', () => {
    expect(deadlineText(d({}))).toBe('Draft CAPA by Thu 19 Nov · 3 days left');
    expect(deadlineText(d({ days_left: 1, state: 'soon' }))).toBe('Draft CAPA by Thu 19 Nov · 1 day left');
    expect(deadlineText(d({ days_left: 0, state: 'soon' }))).toBe('Draft CAPA by Thu 19 Nov · due today');
  });
  it('says how late', () => {
    expect(deadlineText(d({ days_left: -2, state: 'late' }))).toBe('Draft CAPA by Thu 19 Nov · late by 2 days');
  });
  it('says when it was done, and whether that was after its day', () => {
    expect(deadlineText(d({ key: 'review', due: '2026-11-10', done_on: '2026-11-10', state: 'done' }))).toBe(
      'QPPV review of the report done Tue 10 Nov',
    );
    expect(deadlineText(d({ key: 'submission', due: '2026-11-23', done_on: '2026-11-25', state: 'done' }))).toBe(
      'CAPA submitted done Wed 25 Nov · 2 days late',
    );
  });
  it('the next deadline is the first not done; a closed audit has none', () => {
    const deadlines = [
      d({ key: 'review', state: 'done', done_on: '2026-11-10' }),
      d({ key: 'meeting', state: 'late', days_left: -1 }),
      d({ key: 'draft' }),
    ];
    expect(nextDeadline({ status: 'report_received', deadlines })?.key).toBe('meeting');
    expect(nextDeadline({ status: 'closed', deadlines })).toBeNull();
    expect(nextDeadline({ status: 'report_received', deadlines: [deadlines[0]] })).toBeNull();
  });
});

describe('the CAPA plan', () => {
  it('says when a CAPA is due, how late, or when it was done', () => {
    expect(capaDueText(capa({}))).toBe('Due Thu 19 Nov · 3 days left');
    expect(capaDueText(capa({ due: { due: '2026-11-19', done_on: null, days_left: -3, state: 'late' } }))).toBe(
      'Due Thu 19 Nov · late by 3 days',
    );
    expect(capaDueText(capa({ status: 'effective', done_on: '2026-11-17' }))).toBe('Done Tue 17 Nov');
    expect(capaDueText(capa({ status: 'draft', due_on: null, due: null }))).toBe('No due day yet');
  });
  it('names where each CAPA comes from', () => {
    expect(capaSourceText(capa({}))).toBe('from D001/2026');
    expect(
      capaSourceText(capa({ source: 'audit', deviation_ref: null, audit_title: 'Partner audit 2026', observation_number: 2 })),
    ).toBe('from Audit Partner audit 2026, observation 2');
  });
  it('lists the late ones first, then due within two days, then running, then none, then done', () => {
    const list = [
      capa({ id: 'done', status: 'effective', due: { due: '2026-11-01', done_on: '2026-11-01', days_left: -9, state: 'done' } }),
      capa({ id: 'running', due_on: '2026-12-01', due: { due: '2026-12-01', done_on: null, days_left: 20, state: 'running' } }),
      capa({ id: 'none', status: 'draft', due_on: null, due: null }),
      capa({ id: 'soon', due_on: '2026-11-11', due: { due: '2026-11-11', done_on: null, days_left: 1, state: 'soon' } }),
      capa({ id: 'late2', due_on: '2026-11-05', due: { due: '2026-11-05', done_on: null, days_left: -5, state: 'late' } }),
      capa({ id: 'late1', due_on: '2026-11-01', due: { due: '2026-11-01', done_on: null, days_left: -9, state: 'late' } }),
    ];
    expect(sortCapas(list).map((c) => c.id)).toEqual(['late1', 'late2', 'soon', 'running', 'none', 'done']);
  });
  it('filters by status and by source', () => {
    const list = [
      capa({ id: 'a', source: 'audit', status: 'draft' }),
      capa({ id: 'b', status: 'effective' }),
      capa({ id: 'c', due: { due: '2026-11-01', done_on: null, days_left: -2, state: 'late' } }),
    ];
    expect(filterCapas(list, 'all', 'audit').map((c) => c.id)).toEqual(['a']);
    expect(filterCapas(list, 'open', 'all').map((c) => c.id).sort()).toEqual(['a', 'c']);
    expect(filterCapas(list, 'late', 'deviation').map((c) => c.id)).toEqual(['c']);
    expect(filterCapas(list, 'effective', 'all').map((c) => c.id)).toEqual(['b']);
    expect(capaCounts(list)).toEqual({ open: 2, late: 1, effective: 1 });
  });
  it('finds the CAPAs of a deviation or of an observation', () => {
    const list = [capa({ id: 'x' }), capa({ id: 'y', source: 'audit', deviation_id: null, observation_id: 'o1' })];
    expect(capasOf(list, { deviation: 'd1' }).map((c) => c.id)).toEqual(['x']);
    expect(capasOf(list, { observation: 'o1' }).map((c) => c.id)).toEqual(['y']);
    expect(capasOf(list, {})).toEqual([]);
  });
});

describe('the next steps allowed', () => {
  it('a deviation: investigate, then the CAPA once the level and the root cause are known', () => {
    expect(deviationSteps({ status: 'open', level: null, root_cause: null }, []).map((s) => s.to)).toEqual(['investigating']);
    const [toCapa] = deviationSteps({ status: 'investigating', level: null, root_cause: '' }, []);
    expect(toCapa.blocked).toBe('First QA sets the level and give the root cause.');
    expect(deviationSteps({ status: 'investigating', level: 2, root_cause: 'Missed check' }, [])[0].blocked).toBeNull();
  });
  it('a deviation: the QA Manager approves only with its CAPA, and with a comment', () => {
    const steps = deviationSteps({ status: 'capa', level: 2, root_cause: 'x' }, []);
    expect(steps.map((s) => s.satisfactory)).toEqual([true, false]);
    expect(steps.every((s) => s.needsComment)).toBe(true);
    expect(steps[0].blocked).toBe('Add its CAPA first.');
    expect(deviationSteps({ status: 'capa', level: 2, root_cause: 'x' }, [{ status: 'draft' }])[0].blocked).toBeNull();
  });
  it('a deviation closes only when every CAPA is effective', () => {
    const d = { status: 'approved' as const, level: 2 as const, root_cause: 'x' };
    expect(deviationSteps(d, [{ status: 'effective' }, { status: 'done' }])[0].blocked).toBe('A CAPA is not effective yet.');
    expect(deviationSteps(d, [{ status: 'effective' }])[0].blocked).toBeNull();
    expect(deviationSteps({ ...d, status: 'closed' }, [])).toEqual([]);
  });
  it('an audit: report, CAPA submitted, then closed with the closure confirmed and every CAPA effective', () => {
    const a = { report_received_on: null, closure_confirmed_on: null };
    expect(auditSteps({ ...a, status: 'planned' }, [])[0]).toMatchObject({ to: 'report_received', needsDay: true });
    expect(auditSteps({ ...a, status: 'report_received' }, [])[0].to).toBe('capa_submitted');
    const close = auditSteps({ ...a, status: 'capa_submitted' }, [{ status: 'in_progress' }, { status: 'draft' }])[0];
    expect(close).toMatchObject({ to: 'closed', needsComment: true, blocked: '2 CAPAs are not effective yet.' });
    expect(auditSteps({ ...a, status: 'closed' }, [])).toEqual([]);
  });
  it('a CAPA: approved with an owner and a due day, done with the evidence, then effective or not', () => {
    expect(capaSteps({ status: 'draft', owner_id: null, owner_other: null, due_on: '2026-11-19' })[0].blocked).toBe(
      'Give it an owner and a due day first.',
    );
    expect(capaSteps({ status: 'draft', owner_id: null, owner_other: 'Head of QA', due_on: '2026-11-19' })[0].blocked).toBeNull();
    expect(capaSteps({ status: 'approved', owner_id: 'p', owner_other: null, due_on: 'x' }).map((s) => s.to)).toEqual(['in_progress']);
    expect(capaSteps({ status: 'in_progress', owner_id: 'p', owner_other: null, due_on: 'x' })[0].needsEvidence).toBe(true);
    expect(capaSteps({ status: 'done', owner_id: 'p', owner_other: null, due_on: 'x' }).map((s) => s.to)).toEqual([
      'effective',
      'not_effective',
    ]);
    expect(capaSteps({ status: 'effective', owner_id: 'p', owner_other: null, due_on: 'x' })).toEqual([]);
  });
});

describe('the history and a stale write', () => {
  it('says each step in words, with the fields a change touched', () => {
    expect(historyWords({ kind: 'deviation', step: 'updated', after: { root_cause: 'x', inv_training: 'y' } })).toBe(
      'Changed: root cause, training status',
    );
    expect(historyWords({ kind: 'deviation', step: 'level_set', after: { level: 3 } })).toBe('Level set to 3');
    expect(historyWords({ kind: 'observation', step: 'opened', after: null })).toBe('Observation added');
    expect(historyWords({ kind: 'capa', step: 'not_effective', after: null })).toBe('Not effective: back to work');
  });
  it('knows a write refused because the record moved', () => {
    expect(isStale({ code: 'PH409', message: 'x' })).toBe(true);
    expect(isStale({ message: 'STALE_QUALITY: someone else changed this record' })).toBe(true);
    expect(isStale({ code: '22023', message: 'Nothing changed.' })).toBe(false);
    expect(isStale(null)).toBe(false);
  });
});

describe('proposed deviations (0108)', () => {
  function proposal(over: Partial<DeviationProposal>): DeviationProposal {
    return {
      id: 'p',
      source_kind: 'capa',
      source_ref: 'CAPA-001/2026',
      ingredient_id: null,
      title: 'CAPA not done by its due day',
      description: 'CAPA-001/2026 (from deviation D001/2026) was due on Tue 3 Nov 2026.',
      occurred_on: '2026-11-03',
      detected_on: '2026-11-04',
      patient_safety: false,
      regulatory_compliance: true,
      document_quality: false,
      status: 'proposed',
      dismissed_reason: null,
      deviation_id: null,
      deviation_ref: null,
      decided_by: null,
      decided_at: null,
      ...over,
    };
  }

  it('lists only the proposals still waiting, oldest miss first', () => {
    const list = [
      proposal({ id: 'b', occurred_on: '2026-11-05' }),
      proposal({ id: 'done', status: 'dismissed', occurred_on: '2026-11-01' }),
      proposal({ id: 'a', occurred_on: '2026-11-02' }),
      proposal({ id: 'rec', status: 'confirmed', occurred_on: '2026-11-01' }),
    ];
    expect(waitingProposals(list).map((p) => p.id)).toEqual(['a', 'b']);
  });

  it('says when it was due, when it was found and how late', () => {
    expect(proposalDueText(proposal({}))).toBe('Was due Tue 3 Nov 2026 · found Wed 4 Nov 2026 (1 day late)');
    expect(proposalDueText(proposal({ detected_on: '2026-11-06' }))).toContain('(3 days late)');
  });
});
