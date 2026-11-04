import type { ReactNode } from 'react';
import { cx } from './cx';
import { STATUS_LABEL } from '../lib/labels';
import type { IssueStatus, SourceHealth } from '../lib/types';
import { HEALTH_LABEL } from '../lib/labels';

type Tone = 'neutral' | 'blue' | 'warning' | 'danger' | 'success' | 'quiet';

/** A square, flat label with a 1px rule. */
export function Tag({ tone = 'neutral', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span className={cx('tag', `tag-${tone}`)} title={title}>
      {children}
    </span>
  );
}

/** The review status of a notification: a small square marker in the status colour, then the word. */
export function StatusPill({ status }: { status: IssueStatus }) {
  return (
    <span className={cx('status', `status-${status}`)}>
      <span className="status-marker" aria-hidden />
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Source health in plain words, with a small square swatch. */
export function HealthMark({ health }: { health: SourceHealth }) {
  const h = HEALTH_LABEL[health] ?? HEALTH_LABEL.unknown;
  return (
    <span className={cx('health', `health-${health}`)} title={h.explain}>
      {h.label}
    </span>
  );
}
