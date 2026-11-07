import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { formatDate, formatDateTime, formatNumber } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { supabase } from '../../lib/supabase';
import { Country } from '../../ui/Flag';
import { ErrorNote, Loading } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { pageState, pageTotals, sortPages, watchSummary, type PageState, type WatchPage } from './labelWatch';

const STATE: Record<PageState, { label: string; tone: 'success' | 'warning' | 'danger' | 'quiet' | 'neutral' }> = {
  read: { label: 'Read', tone: 'success' },
  unread: { label: 'Read, with gaps', tone: 'warning' },
  not_run: { label: 'Not read yet', tone: 'neutral' },
  failing: { label: 'Last run failed', tone: 'danger' },
  off: { label: 'Switched off', tone: 'danger' },
  blocked: { label: 'Not read', tone: 'quiet' },
};

export function useLabelWatch(ingredientId: string) {
  return useQuery({
    queryKey: ['label-watch', ingredientId],
    enabled: Boolean(ingredientId),
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<WatchPage[] | null>(await supabase.rpc('label_watch', { p_ingredient: ingredientId })) ?? [],
  });
}

/**
 * Under "Label changes" (section 03): every database page of her list, with what the weekly label watch read
 * there for this ingredient (label_watch, 0091): the products listed, the labels read, those that could not be
 * read and why, the newest label date and the newest change detected. A page that is not read says why.
 */
export function LabelWatch({ ingredientId }: { ingredientId: string }) {
  const q = useLabelWatch(ingredientId);
  if (q.isPending) return <Loading label="Reading what the label watch read" />;
  if (q.isError) {
    return <ErrorNote title="What the label watch read could not be shown." error={q.error} onRetry={() => void q.refetch()} />;
  }
  const pages = sortPages(q.data);
  if (!pages.length) return null;
  const sum = watchSummary(pages);
  return (
    <details className="lab-watch">
      <summary>
        <span className="lab-watch-title">Databases read</span>
        <span className="lab-watch-counts">
          {sum.read} of {sum.pages} pages read · {formatNumber(sum.products)}{' '}
          {sum.products === 1 ? 'product' : 'products'}
          {sum.unread ? ` · ${sum.unread} ${sum.unread === 1 ? 'label' : 'labels'} unread` : ''}
          {sum.failing ? ` · ${sum.failing} failing` : ''}
          {sum.blocked ? ` · ${sum.blocked} not read` : ''}
        </span>
      </summary>
      <div className="table-wrap">
        <table className="table lab-watch-table">
          <caption className="visually-hidden">What the label watch read, per database page</caption>
          <thead>
            <tr>
              <th>Database</th>
              <th className="num">Products</th>
              <th className="num">Labels read</th>
              <th>Newest label</th>
              <th>Last change found</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <PageRow key={p.page_id} p={p} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="lab-gap-quiet">
        Read weekly, for our ingredients only. Centrally authorised medicines are read once, through EMA. Products
        are those the database lists as authorised now; a list that broke off switches no product off.
      </p>
    </details>
  );
}

function PageRow({ p }: { p: WatchPage }) {
  const state = pageState(p);
  const t = pageTotals(p);
  const href = safeHref(p.url);
  const shown = STATE[state];
  return (
    <tr>
      <td>
        <Country name={p.country_name} code={p.country_code} />
        <div>
          {href ? (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {p.label}
            </a>
          ) : (
            p.label
          )}
        </div>
        <div className="scr-quiet">{p.regulator}</div>
      </td>
      {state === 'blocked' ? (
        <td colSpan={4} className="lab-watch-note">
          {p.note ?? 'Not read by the app.'}
        </td>
      ) : (
        <>
          <td className="num">{formatNumber(t.products)}</td>
          <td className="num">
            {formatNumber(t.labels_read)}
            {t.waiting ? <div className="scr-quiet">{t.waiting} waiting their turn</div> : null}
          </td>
          <td>{t.latest_label_date ? formatDate(t.latest_label_date) : <span className="muted">—</span>}</td>
          <td>{t.latest_change_at ? formatDateTime(t.latest_change_at) : <span className="muted">None yet</span>}</td>
        </>
      )}
      <td>
        <Tag tone={shown.tone}>{shown.label}</Tag>
        {t.listed_at ? <div className="scr-quiet">Listed {formatDateTime(t.listed_at)}</div> : null}
        {t.run_error ? <div className="lab-watch-error">{t.run_error}</div> : null}
        {t.gaps.length ? <div className="lab-watch-error">List broke off: {t.gaps.join('; ')}</div> : null}
        {t.errors.length ? (
          <ul className="lab-watch-errors">
            {t.errors.map((e) => (
              <li key={`${e.national_id}-${e.at}`}>
                <strong>{e.product}</strong> not read{e.at ? ` (${formatDateTime(e.at)})` : ''}: {e.error}
              </li>
            ))}
          </ul>
        ) : null}
      </td>
    </tr>
  );
}
