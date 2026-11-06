// Decisions recorded from the Ingredients screen. Pure helpers, no I/O.

import type { IssueStatus } from '../../lib/types';
import type { Decision, IngredientScreenData, Mention } from './types';

/** Her two decisions (6 Nov 2026): Concerns us, or Doesn't concern us with a reason. */
export const DECISIONS: { to: 'relevant' | 'not_relevant'; label: string; hint: string }[] = [
  { to: 'relevant', label: 'Concerns us', hint: 'It concerns our products and needs action or follow-up.' },
  { to: 'not_relevant', label: "Doesn't concern us", hint: 'It does not concern our products. Say why.' },
];

/** Each status in her words. Reviewed comes from the older screens and still waits for a decision. */
export const DECISION_LABEL: Record<IssueStatus, string> = {
  new: 'No decision yet',
  reviewed: 'Reviewed, no decision yet',
  relevant: 'Concerns us',
  not_relevant: "Doesn't concern us",
};

/** The decisions that can follow the notice's status: never the one already taken. */
export function choicesFor(status: IssueStatus): typeof DECISIONS {
  return DECISIONS.filter((d) => d.to !== status);
}

/** Doesn't concern us needs a reason, as the database requires. */
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
