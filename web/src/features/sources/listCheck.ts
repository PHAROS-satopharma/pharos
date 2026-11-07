import { useQuery } from '@tanstack/react-query';
import { fetchAllPages } from '../../lib/api';
import { formatCairoDate, formatNumber } from '../../lib/format';
import { supabase } from '../../lib/supabase';

/** One source's weekly list check (list_check, 0096; collectors/completeness.py). */
export interface ListCheckRow {
  source_id: string;
  checked_at: string;
  listed: number;
  stored: number;
  older: number;
  missing: number;
  filtered: number;
  missing_items: { external_id: string; title: string; url: string; published: string | null }[];
  complete: boolean;
  error: string | null;
}

/** The latest row per source, from rows newest first. */
export function latestBySource(rows: ListCheckRow[]): Map<string, ListCheckRow> {
  const out = new Map<string, ListCheckRow>();
  for (const r of rows) if (!out.has(r.source_id)) out.set(r.source_id, r);
  return out;
}

/** The last five weeks of list checks, the latest per source. */
export function useListChecks() {
  return useQuery({
    queryKey: ['list-checks'],
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const since = new Date(Date.now() - 35 * 86_400_000).toISOString();
      return latestBySource(
        await fetchAllPages<ListCheckRow>(
          async (from, to) =>
            await supabase
              .from('list_check')
              .select('source_id,checked_at,listed,stored,older,missing,filtered,missing_items,complete,error')
              .gte('checked_at', since)
              .order('checked_at', { ascending: false })
              .range(from, to),
        ),
      );
    },
  });
}

const notices = (n: number) => `${formatNumber(n)} ${n === 1 ? 'notice' : 'notices'}`;

/** One line under a source on the Sources page: its own list, read whole, against what PHAROS holds. */
export function listLine(r: ListCheckRow | undefined): { text: string; needsLook: boolean } | null {
  if (!r) return null;
  const when = `Whole list checked ${formatCairoDate(r.checked_at)}`;
  if (!r.complete && !r.listed) return { text: `${when}: not read (${r.error ?? 'no reason given'}).`, needsLook: true };
  const parts: string[] = [];
  if (r.missing) {
    const newest = r.missing_items[0];
    parts.push(
      `${formatNumber(r.missing)} of ${notices(r.listed)} listed ${r.missing === 1 ? 'is' : 'are'} not stored` +
        (newest ? `, newest “${newest.title}”` : ''),
    );
  } else {
    parts.push(r.listed ? `all ${notices(r.stored)} listed are stored` : 'its list is empty');
  }
  if (r.older) parts.push(`${formatNumber(r.older)} older than the kept history`);
  if (r.filtered) parts.push(`${formatNumber(r.filtered)} left out by its filters`);
  if (!r.complete) parts.push(`part of the list not read: ${r.error ?? 'no reason given'}`);
  return { text: `${when}: ${parts.join(' · ')}.`, needsLook: r.missing > 0 || !r.complete };
}
