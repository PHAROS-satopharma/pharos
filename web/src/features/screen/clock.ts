// The five-day clock to the Egyptian Drug Authority (migrations 0041 and 0050), as finding_state() answers it per
// notice. Pure helpers, no I/O. The database decides the clock; these only word it and keep the screen's copy of
// it in step after a decision, a report sent or a report withdrawn.

import { formatDate } from '../../lib/format';
import type { IssueStatus } from '../../lib/types';
import { addDays, dayCount } from './range';
import type { AuthoritySent, FindingState, Findings, Mention } from './types';

/** The notices on a screen, each once: what finding_state() is asked for. */
export function issueIdsOf(data: { regulators: { mentions: Mention[] }[]; label_changes: Mention[] }): string[] {
  const ids = new Set<string>();
  for (const r of data.regulators) for (const m of r.mentions) if (m.issue_id) ids.add(m.issue_id);
  for (const m of data.label_changes) if (m.issue_id) ids.add(m.issue_id);
  return [...ids];
}

const dueFmt = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });

/** "Tue 11 Nov" for a calendar day (YYYY-MM-DD). */
export function dueLabel(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day);
  if (!m) return day;
  return dueFmt.format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))).replace(',', '');
}

function days(n: number): string {
  return `${n} ${n === 1 ? 'day' : 'days'}`;
}

/** The clock in one line under the decision, or nothing while it is off. */
export function clockLine(f: FindingState | null | undefined): string | null {
  if (!f) return null;
  switch (f.clock) {
    case 'running':
      return f.days_left === 0
        ? `Authority: due today, ${dueLabel(f.due)}`
        : `Authority: due ${dueLabel(f.due)}, ${days(f.days_left)} left`;
    case 'late':
      return `Authority: late by ${days(-f.days_left)} (was due ${dueLabel(f.due)})`;
    case 'sent':
      return f.sent
        ? `Sent to the authority ${formatDate(f.sent.on)}${f.sent.reference ? ` · ref ${f.sent.reference}` : ''}`
        : 'Sent to the authority';
    default:
      return null;
  }
}

/** "Sent to the authority" is offered only while the clock runs or is late. */
export function canSend(f: FindingState | null | undefined): boolean {
  return f?.clock === 'running' || f?.clock === 'late';
}

/** The database refused the report: the notice's latest decision is not Concerns us any more, or this decision
 *  was reported already (SQLSTATE PH409). The screen reloads and shows the notice as it is now. */
export function isClockRefusal(error: { code?: string; message?: string } | null | undefined): boolean {
  if (!error) return false;
  const msg = error.message ?? '';
  return error.code === 'PH409' || msg.startsWith('NO_CONCERN') || msg.startsWith('ALREADY_SENT');
}

/** Days from `today` to `due`: negative when late. */
export function daysUntil(today: string, due: string): number {
  return dayCount(today, due) - 1;
}

/** A running clock as seen on Cairo day `today`: late once today is past the due day. */
export function runningClock(f: FindingState, today: string): FindingState {
  const left = daysUntil(today, f.due);
  return { ...f, days_left: left, clock: left < 0 ? 'late' : 'running', sent: null };
}

/** What holds the clocks of notices: the screen's data, or a page of papers (PaperPage). */
export interface WithFindings {
  findings: Findings;
}

function patch<T extends WithFindings>(data: T, issueId: string, next: (f: FindingState) => FindingState): T {
  const f = data.findings[issueId];
  if (!f) return data;
  const findings: Findings = { ...data.findings, [issueId]: next(f) };
  return { ...data, findings };
}

/** The screen (or a page of papers) after a report to the authority was recorded: the clock stops on every mention
 *  and paper of the notice. */
export function withSent<T extends WithFindings>(data: T, issueId: string, sent: AuthoritySent): T {
  return patch(data, issueId, (f) => ({ ...f, clock: 'sent', sent }));
}

/** The screen after a decision: Concerns us starts (or keeps) the clock — or finds the notice already sent, since a
 *  report to the authority is never forgotten; anything else switches the clock off and keeps the report. The due
 *  day is the database's and does not move with a decision (day zero is the day PHAROS first showed the notice). */
export function withClockDecision<T extends WithFindings>(data: T, issueId: string, to: IssueStatus, today: string): T {
  return patch(data, issueId, (f) => {
    if (to !== 'relevant') return { ...f, clock: 'off' };
    return f.sent ? { ...f, clock: 'sent' } : runningClock(f, today);
  });
}

/** The screen after a wrong report was withdrawn: the clock runs again from the same due day. */
export function withWithdrawn<T extends WithFindings>(data: T, issueId: string, today: string): T {
  return patch(data, issueId, (f) => runningClock(f, today));
}

/** The latest day a report can be dated: today in Cairo. */
export function latestSentDay(today: string): string {
  return today;
}

/** The first day that makes sense for a report: the notice's day zero (earlier is a typo). */
export function earliestSentDay(f: FindingState | null | undefined): string | undefined {
  return f ? addDays(f.day_zero, 0) : undefined;
}
