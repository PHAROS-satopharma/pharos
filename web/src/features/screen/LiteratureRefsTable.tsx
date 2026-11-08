// The ingredient's literature, reference by reference (Dr Sama, 8 Nov 2026; migration 0101): for each of her
// Global and Local references, how it was screened in these days and what was found — "Nothing found" in words,
// so the negative result is on the screen even in a week with no paper.

import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { formatDateTime, formatNumber } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { Loading, Notice } from '../../ui/States';
import { SCOPE_TITLE, refFound, type RefWeek } from '../sources/literatureRefs';

export function useIngredientRefs(ingredientId: string, from: string, to: string) {
  return useQuery({
    queryKey: ['ingredient-literature-refs', ingredientId, from, to],
    queryFn: async () =>
      unwrap<RefWeek[] | null>(
        await supabase.rpc('literature_refs_week', { p_ingredient: ingredientId, p_from: from, p_to: to }),
      ) ?? [],
  });
}

/** How the reference was screened in these days. */
export function screenedText(r: RefWeek, when: (iso: string) => string): string {
  if (r.by_hand) {
    return r.check ? `By hand — ${r.check.checked_by}, ${when(r.check.checked_at)}` : 'By hand — not checked in these days';
  }
  if (r.searches === 0) return 'Not searched by the app in these days';
  const failed = r.failed_reads ?? 0;
  return (
    `By the app — ${formatNumber(r.searches)} ${r.searches === 1 ? 'search' : 'searches'}` +
    (r.last_searched ? `, last ${when(r.last_searched)}` : '') +
    (failed ? `; ${formatNumber(failed)} ${failed === 1 ? 'read' : 'reads'} failed` : '')
  );
}

export function LiteratureRefsTable({ ingredientId, from, to }: { ingredientId: string; from: string; to: string }) {
  const refs = useIngredientRefs(ingredientId, from, to);
  if (refs.isPending) return <Loading label="Reading the literature references" />;
  if (refs.isError) {
    return <Notice tone="error">The literature references could not be read: {errorMessage(refs.error)}</Notice>;
  }
  if (!refs.data.length) return null;
  return (
    <table className="scr-queries scr-refs">
      <caption className="micro">Literature references: how each was screened in these days, and what was found</caption>
      <thead>
        <tr>
          <th scope="col">Reference</th>
          <th scope="col">Screened</th>
          <th scope="col">Found</th>
        </tr>
      </thead>
      <tbody>
        {refs.data.map((r) => {
          const href = r.url ? safeHref(r.url) : null;
          const found = refFound(r);
          return (
            <tr key={r.id}>
              <th scope="row">
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {r.name}
                  </a>
                ) : (
                  r.name
                )}{' '}
                <span className="scr-quiet">{SCOPE_TITLE[r.scope]}</span>
              </th>
              <td className="scr-refs-how">{screenedText(r, formatDateTime)}</td>
              <td className={found === 'Nothing found' ? 'scr-refs-none' : undefined}>
                {found}
                {r.check?.result === 'found' && r.check.note ? ` — ${r.check.note}` : ''}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
