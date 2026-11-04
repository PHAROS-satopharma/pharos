import type { ReactNode, TableHTMLAttributes } from 'react';
import { cx } from './cx';

/** A table on 1px rules. It scrolls inside its own box on narrow screens, never the page. */
export function Table({ className, children, ...rest }: TableHTMLAttributes<HTMLTableElement> & { children: ReactNode }) {
  return (
    <div className="table-wrap">
      <table className={cx('table', className)} {...rest}>
        {children}
      </table>
    </div>
  );
}
