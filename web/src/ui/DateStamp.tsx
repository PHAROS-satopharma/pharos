import { formatDate } from '../lib/format';

/** A date as a register entry: the day large, the month and year small beneath ("4" over "Nov 2026"). */
export function DateStamp({ value }: { value: string | null | undefined }) {
  const text = formatDate(value);
  const m = /^(\d{1,2}) (.+)$/.exec(text);
  if (!m) return <span className="datestamp-rest">{text}</span>;
  return (
    <span className="datestamp">
      <span className="datestamp-day">{m[1]}</span>
      <span className="datestamp-rest">{m[2]}</span>
    </span>
  );
}
