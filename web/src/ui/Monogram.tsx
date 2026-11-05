import { cx } from './cx';

/** Up to two initials from a name: "Omar Gawish" → "OG". */
export function initials(name: string | null | undefined): string {
  const parts = (name ?? '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0][0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? '') : '';
  return (first + last).toUpperCase();
}

/** The person's initials in a navy square. Decorative: the name always stands beside it. */
export function Monogram({ name, large }: { name: string | null | undefined; large?: boolean }) {
  return (
    <span className={cx('monogram', large && 'monogram-lg')} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
