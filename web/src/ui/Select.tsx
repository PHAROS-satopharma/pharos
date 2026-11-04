import { forwardRef, type SelectHTMLAttributes } from 'react';
import { cx } from './cx';

export interface Option {
  value: string;
  label: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  options?: Option[];
  /** A first option with an empty value, e.g. "Every country". */
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, options, placeholder, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={cx('field', 'field-select', className)} {...rest}>
      {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
      {options?.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
      {children}
    </select>
  );
});
