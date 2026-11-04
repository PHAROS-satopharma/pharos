import { useCountryIndex } from '../lib/regulators';

/** The two-letter country code in a small 1px-ruled mono box. Decorative: the name stands beside it. */
export function Flag({ code }: { code: string | null | undefined }) {
  if (!code || !/^[A-Za-z]{2}$/.test(code)) return null;
  return (
    <span className="cc" aria-hidden="true">
      {code.toUpperCase()}
    </span>
  );
}

/** A country name with its code box. Pass the name (as the view gives it) or the code. */
export function Country({ name, code }: { name?: string | null; code?: string | null }) {
  const idx = useCountryIndex();
  const shownName = name || idx.nameOf(code);
  const shownCode = code ?? idx.codeOf(name);
  if (!shownName) return <span className="muted">—</span>;
  return (
    <span className="country">
      <Flag code={shownCode} />
      <span>{shownName}</span>
    </span>
  );
}
