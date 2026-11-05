import type { SignalStage, SignalStep } from './types';

/** The steps a reviewer may take from a stage, in the order they are offered. */
export function stepsFor(stage: SignalStage): SignalStep[] {
  switch (stage) {
    case 'validation':
      return ['validated', 'not_validated', 'assigned', 'note'];
    case 'assessment':
      return ['assessed', 'prioritised', 'assigned', 'note'];
    case 'action':
      return ['action_done', 'prioritised', 'assigned', 'note'];
    case 'closed':
      return ['reopened', 'note'];
  }
}

function dayNumber(d: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86_400_000 : null;
}

/** Whole calendar days from `today` to `due` (both YYYY-MM-DD); negative once it has passed. */
export function daysUntil(due: string, today: string): number | null {
  const a = dayNumber(due);
  const b = dayNumber(today);
  return a === null || b === null ? null : a - b;
}

/** "Due today", "Due in 3 days", "1 day overdue" — for the current stage's due day in Cairo. */
export function dueWords(due: string | null, today: string): string {
  if (!due) return 'No due date';
  const n = daysUntil(due, today);
  if (n === null) return 'No due date';
  if (n === 0) return 'Due today';
  if (n > 0) return `Due in ${n} ${n === 1 ? 'day' : 'days'}`;
  return `${-n} ${n === -1 ? 'day' : 'days'} overdue`;
}
