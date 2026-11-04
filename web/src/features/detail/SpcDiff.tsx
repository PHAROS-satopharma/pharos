import { useMemo } from 'react';
import { diffWords, type DiffPart } from '../../lib/wordDiff';
import { formatDate, formatDateTime } from '../../lib/format';
import type { SpcChangeRow, SpcDiffSection } from './queries';
import { Country } from '../../ui/Flag';

function Side({ parts, side }: { parts: DiffPart[]; side: 'before' | 'after' }) {
  const hide = side === 'before' ? 'add' : 'del';
  let pos = 0;
  return (
    <>
      {parts
        .filter((p) => p.op !== hide)
        .map((p) => {
          const key = pos;
          pos += p.text.length;
          if (p.op === 'same') return <span key={key}>{p.text}</span>;
          return p.op === 'del' ? (
            <del key={key} className="diff-del">
              {p.text}
            </del>
          ) : (
            <ins key={key} className="diff-ins">
              {p.text}
            </ins>
          );
        })}
    </>
  );
}

function SectionDiff({ s }: { s: SpcDiffSection }) {
  const parts = useMemo(() => diffWords(s.before, s.after), [s.before, s.after]);
  return (
    <div className="diff-section">
      <div className="diff-section-name micro">Section {s.section}</div>
      <div className="diff-grid">
        <div className="diff-col">
          <span className="micro soft">Before</span>
          <div className="diff-text" dir="auto">
            {s.before ? <Side parts={parts} side="before" /> : <span className="soft">This section did not exist.</span>}
          </div>
        </div>
        <div className="diff-col">
          <span className="micro soft">After</span>
          <div className="diff-text" dir="auto">
            {s.after ? <Side parts={parts} side="after" /> : <span className="soft">This section was removed.</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

export function SpcDiff({ changes }: { changes: SpcChangeRow[] }) {
  if (changes.length === 0) {
    return <p className="soft">No change to the product information is recorded for this notification.</p>;
  }
  return (
    <div className="spc">
      {changes.map((c) => (
        <article key={c.id} className="spc-change">
          <header className="spc-head">
            {c.spc_product ? <Country code={c.spc_product.country_code} /> : null}
            <span className="spc-product" dir="auto">
              {c.spc_product?.product_name ?? 'Product'}
            </span>
            {c.spc_product?.mah ? <span className="soft" dir="auto">{c.spc_product.mah}</span> : null}
            {c.spc_product?.url ? (
              <a href={c.spc_product.url} target="_blank" rel="noopener noreferrer" className="small">
                Product information <span aria-hidden>↗</span>
              </a>
            ) : null}
          </header>
          <p className="soft small">
            Text dated {formatDate(c.from_snap?.doc_date)} compared with {formatDate(c.to_snap?.doc_date)} · found{' '}
            {formatDateTime(c.created_at)} · {c.diff.length} {c.diff.length === 1 ? 'section' : 'sections'} changed.
            Shown in the language of the product information; struck-through words were removed, underlined words were
            added.
          </p>
          {c.diff.map((s, i) => (
            <SectionDiff key={`${c.id}-${s.section}-${i}`} s={s} />
          ))}
        </article>
      ))}
    </div>
  );
}
