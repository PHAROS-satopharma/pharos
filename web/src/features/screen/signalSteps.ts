// The signal steps inside a finding (migration 0042). Pure helpers, no I/O: which step comes next at each
// stage, what a step needs, how the due day is worded, and how the screen's copy of the signal is replaced
// after a step. The database decides the stages and the due days.

import { ACTION_OUTCOMES, SIGNAL_STAGES, type SignalOutcome, type SignalStage, type SignalStep } from '../../lib/types';
import { dueLabel } from './clock';
import type { FindingSignal, Findings, IngredientScreenData } from './types';

/** A step she can take from the signal's stage, and what the form must ask for. */
export interface NextStep {
  step: SignalStep;
  /** The button and the heading of its form. */
  label: string;
  /** Validated needs a priority. */
  needsPriority: boolean;
  /** Assessed needs an outcome (and a due date when the outcome opens an action). */
  needsOutcome: boolean;
  /** The label of the comment field. */
  commentLabel: string;
  /** Not a signal is the quiet, red answer. */
  tone: 'primary' | 'danger';
}

/** The steps that follow each stage, as signal_take_step allows them; the recommended one first. */
export function nextSteps(stage: SignalStage): NextStep[] {
  switch (stage) {
    case 'validation':
      return [
        {
          step: 'validated',
          label: 'It is a signal',
          needsPriority: true,
          needsOutcome: false,
          commentLabel: 'Why it is a signal (required)',
          tone: 'primary',
        },
        {
          step: 'not_validated',
          label: 'Not a signal',
          needsPriority: false,
          needsOutcome: false,
          commentLabel: 'Why it is not a signal (required)',
          tone: 'danger',
        },
      ];
    case 'assessment':
      return [
        {
          step: 'assessed',
          label: 'Record the assessment',
          needsPriority: false,
          needsOutcome: true,
          commentLabel: 'The conclusion (required)',
          tone: 'primary',
        },
      ];
    case 'action':
      return [
        {
          step: 'action_done',
          label: 'Action done',
          needsPriority: false,
          needsOutcome: false,
          commentLabel: 'What was done, with its reference (required)',
          tone: 'primary',
        },
      ];
    case 'closed':
      return [
        {
          step: 'reopened',
          label: 'Reopen',
          needsPriority: false,
          needsOutcome: false,
          commentLabel: 'Why it is reopened (required)',
          tone: 'primary',
        },
      ];
  }
}

/** An outcome that opens an action needs the day the action is due. */
export function needsDue(outcome: SignalOutcome | null | undefined): boolean {
  return Boolean(outcome && ACTION_OUTCOMES.includes(outcome));
}

/** The four stages as the chain draws them. */
export const CHAIN_LABEL: Record<SignalStage, string> = {
  validation: 'Validate',
  assessment: 'Assess',
  action: 'Action',
  closed: 'Closed',
};

export interface ChainLink {
  stage: SignalStage;
  label: string;
  state: 'done' | 'current' | 'todo';
}

/** The chain Validate → Assess → Action → Closed with the current stage lit and the ones before it done. */
export function chainOf(stage: SignalStage): ChainLink[] {
  const at = SIGNAL_STAGES.indexOf(stage);
  return SIGNAL_STAGES.map((s, i) => ({
    stage: s,
    label: CHAIN_LABEL[s],
    state: i < at ? 'done' : i === at ? 'current' : 'todo',
  }));
}

/** "Validate by Sun 6 Dec", and whether it is late; nothing once closed or without a due day. */
export function stepDue(signal: FindingSignal): { text: string; late: boolean } | null {
  if (signal.stage === 'closed' || !signal.next_due) return null;
  return { text: `${CHAIN_LABEL[signal.stage]} by ${dueLabel(signal.next_due)}`, late: signal.overdue };
}

/** The database refused the step: the signal moved since the screen read it (SQLSTATE PH409, STALE_SIGNAL). */
export function isStaleSignal(error: { code?: string; message?: string } | null | undefined): boolean {
  if (!error) return false;
  return error.code === 'PH409' || (error.message ?? '').startsWith('STALE_SIGNAL');
}

/** The screen after a step: the notice's signal is replaced; its clock and the other notices are untouched. */
export function withSignal(data: IngredientScreenData, issueId: string, signal: FindingSignal | null): IngredientScreenData {
  const f = data.findings[issueId];
  if (!f) return data;
  const findings: Findings = { ...data.findings, [issueId]: { ...f, signal } };
  return { ...data, findings };
}
