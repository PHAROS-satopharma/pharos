import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { fetchAllPages, unwrap } from '../../lib/api';
import type { Source, SourceRun } from '../../lib/types';

export interface SourceWithRegulator extends Source {
  regulator: { id: string; name: string; country_code: string; country_name: string; languages: string[] } | null;
}

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: async () =>
      unwrap<SourceWithRegulator[] | null>(
        await supabase
          .from('source')
          .select(
            'id,regulator_id,kind,channel,url,parser,languages,schedule,enabled,origin,health,consecutive_failures,' +
              'last_ok_at,last_item_at,expected_max_gap_days,notes,created_at,' +
              'regulator:regulator_id(id,name,country_code,country_name,languages)',
          )
          .order('id'),
      ) ?? [],
  });
}

export type RunSlice = Pick<
  SourceRun,
  'source_id' | 'started_at' | 'finished_at' | 'http_status' | 'items_seen' | 'items_new' | 'items_matched' | 'error'
>;

const RUN_COLUMNS = 'source_id,started_at,finished_at,http_status,items_seen,items_new,items_matched,error';

/** Every source_run between two instants (ISO), paged past the 1,000-row ceiling. */
export function fetchRuns(fromIso: string, toIso?: string): Promise<RunSlice[]> {
  return fetchAllPages<RunSlice>(async (from, to) => {
    let q = supabase.from('source_run').select(RUN_COLUMNS).gte('started_at', fromIso);
    if (toIso) q = q.lt('started_at', toIso);
    return await q.order('started_at', { ascending: false }).range(from, to);
  });
}

export interface RunTotals {
  runs: number;
  failed: number;
  seen: number;
  fresh: number;
  matched: number;
  lastRun: string | null;
  lastError: string | null;
}

export function isFailed(r: RunSlice): boolean {
  return Boolean(r.error) || (r.http_status != null && r.http_status >= 400);
}

/** Totals per source. Runs must be newest first. */
export function totalsBySource(runs: RunSlice[]): Map<string, RunTotals> {
  const out = new Map<string, RunTotals>();
  for (const r of runs) {
    let t = out.get(r.source_id);
    if (!t) {
      t = { runs: 0, failed: 0, seen: 0, fresh: 0, matched: 0, lastRun: null, lastError: null };
      out.set(r.source_id, t);
    }
    t.runs += 1;
    if (isFailed(r)) {
      t.failed += 1;
      if (t.lastError === null) t.lastError = r.error ?? `HTTP ${r.http_status ?? ''}`.trim();
    }
    t.seen += r.items_seen ?? 0;
    t.fresh += r.items_new ?? 0;
    t.matched += r.items_matched ?? 0;
    const at = r.finished_at ?? r.started_at;
    if (!t.lastRun || at > t.lastRun) t.lastRun = at;
  }
  return out;
}
