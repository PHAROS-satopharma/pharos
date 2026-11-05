import type { ReactNode } from 'react';
import { cx } from './cx';
import { formatNumber } from '../lib/format';

/** A row of figures on a hairline grid. */
export function StatRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="stats" role="group" aria-label={label}>
      {children}
    </div>
  );
}

/**
 * One figure: the number large in the serif, its words beneath after a square in the tone colour. With
 * `onClick` it is a button that filters the list, and `active` marks the filter in force.
 */
export function Stat({
  value,
  label,
  tone,
  active,
  onClick,
  title,
}: {
  value: number | null | undefined;
  label: string;
  tone?: string;
  active?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const body = (
    <>
      <span className="stat-value">{value == null ? '—' : formatNumber(value)}</span>
      <span className="stat-label">{label}</span>
    </>
  );
  const className = cx('stat', tone && `stat-${tone}`);
  if (onClick) {
    return (
      <button type="button" className={className} aria-pressed={Boolean(active)} onClick={onClick} title={title}>
        {body}
      </button>
    );
  }
  return (
    <div className={className} title={title}>
      {body}
    </div>
  );
}
