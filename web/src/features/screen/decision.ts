// Decisions recorded from the Ingredients screen. Pure helpers, no I/O.

import type { IssueStatus } from '../../lib/types';
import type { Decision, IngredientScreenData, Mention } from './types';

export const DECISIONS: { to: Exclude<IssueStatus, 'new'>; label: string; hint: string }[] = [
  { to: 'reviewed', label: 'Reviewed', hint: 'Read, decision still to come.' },
  { to: 'relevant', label: 'Relevant', hint: 'It concerns our products and needs action or follow-up.' },
  { to: 'not_relevant', label: 'Not relevant', hint: 'It does not concern our products. Say why.' },
];

/** The decisions that can follow the notice's status: never back to New, never the same status again. */
export function choicesFor(status: IssueStatus): typeof DECISIONS {
  return DECISIONS.filter((d) => d.to !== status);
}

/** Not relevant needs a reason, as the database requires. */
export function needsReason(to: IssueStatus | null): boolean {
  return to === 'not_relevant';
}

/** The database refused the decision: the notice's status changed since the screen read it (SQLSTATE PH409). */
export function isStaleDecision(error: { code?: string; message?: string } | null | undefined): boolean {
  if (!error) return false;
  return error.code === 'PH409' || (error.message ?? '').startsWith('STALE_DECISION');
}

function apply(m: Mention, issueId: string, d: Decision): Mention {
  return m.issue_id === issueId ? { ...m, issue_status: d.to_status, decision: d } : m;
}

/** The screen after a decision: every mention filed under the same notice shows it, wherever it is listed. */
export function withDecision(data: IngredientScreenData, issueId: string, d: Decision): IngredientScreenData {
  return {
    ...data,
    regulators: data.regulators.map((r) =>
      r.mentions.some((m) => m.issue_id === issueId)
        ? { ...r, mentions: r.mentions.map((m) => apply(m, issueId, d)) }
        : r,
    ),
    label_changes: data.label_changes.map((m) => apply(m, issueId, d)),
  };
}
