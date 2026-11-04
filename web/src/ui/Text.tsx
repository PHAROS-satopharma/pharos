import type { ReactNode } from 'react';
import { cx } from './cx';

/** The micro label: 10.5px, bold, uppercase, tracked. The one voice of every label. */
export function Micro({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx('micro', className)}>{children}</span>;
}

/** A micro label in the accent-text colour, after a short rule. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span className="eyebrow">
      <span className="eyebrow-rule" aria-hidden />
      {children}
    </span>
  );
}

export function PageHead({
  eyebrow,
  title,
  lede,
  actions,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-text">
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <h1 className="page-title">{title}</h1>
        {lede ? <p className="page-lede">{lede}</p> : null}
      </div>
      {actions ? <div className="page-head-actions">{actions}</div> : null}
    </header>
  );
}

/** A numbered section head on a hairline, so long pages read in order. */
export function SectionHead({ index, title, aside }: { index?: string; title: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section-head">
      <div className="section-head-label">
        {index ? <span className="section-index">{index}</span> : null}
        {index ? <span className="section-tick" aria-hidden /> : null}
        <h2 className="section-title">{title}</h2>
      </div>
      {aside ? <div className="section-aside">{aside}</div> : null}
    </div>
  );
}
