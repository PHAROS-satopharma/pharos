import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { fetchAllPages, unwrap } from '../../lib/api';
import type { Source, SourceRun } from '../../lib/types';

export interface SourceWithRegulator extends Source {
  /** The page a person opens (sources.yaml `page:`, 0032); null for a source added by hand. */
  page_url: string | null;
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
              'last_ok_at,last_item_at,expected_max_gap_days,notes,created_at,page_url,' +
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
  /** The newest run's note or failure reason; null once a later run is clean. */
  lastError: string | null;
}

/**
 * Notes a COMPLETED run carries in source_run.error, mirroring source_run_failed() in
 * the latest migration that defines it (0054; keep the two lists the same). A Health
 * Canada backfill that stopped at its 10-minute budget ("time budget reached: …") read the whole list;
 * this page counted six of them as failed runs on 5 Nov 2026 while the Reports screen did not.
 */
export const RUN_NOTE =
  /^(imap not configured|imap: |[0-9]+ item\(s\) failed; first: |time budget reached: |item cap reached: |[0-9]+ error\(s\); first: |[0-9]+ product\(s\) without label text|out of time: )/;

/**
 * As source_run_failed(): a run failed when its error is not one of the notes above. http_status is only the
 * first answer's status, and a collector that refuses an answer records an error; one that accepts it (openFDA's
 * 404 is "No matches found") completes clean, so the status alone never makes a run failed.
 */
export function isFailed(r: RunSlice): boolean {
  return Boolean(r.error) && !RUN_NOTE.test(r.error ?? '');
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
    const newest = t.runs === 0;
    t.runs += 1;
    const failed = isFailed(r);
    if (failed) t.failed += 1;
    // only the newest run's own note: an older one no longer describes the source
    if (newest && r.error) t.lastError = r.error;
    t.seen += r.items_seen ?? 0;
    t.fresh += r.items_new ?? 0;
    t.matched += r.items_matched ?? 0;
    const at = r.finished_at ?? r.started_at;
    if (!t.lastRun || at > t.lastRun) t.lastRun = at;
  }
  return out;
}

export interface FilteredRow {
  source_id: string;
  title: string;
  reason: string;
  last_seen_at: string;
}

export interface FilteredSummary {
  count: number;
  latest: FilteredRow;
}

/** Per source, how many titles its filters left out (filtered_item, 0074) and the newest one. Rows newest first. */
export function filteredBySource(rows: FilteredRow[]): Map<string, FilteredSummary> {
  const out = new Map<string, FilteredSummary>();
  for (const r of rows) {
    const s = out.get(r.source_id);
    if (s) s.count += 1;
    else out.set(r.source_id, { count: 1, latest: r });
  }
  return out;
}

/** What each source's keyword or category filters left out; read only while the technical details are shown. */
export function useFiltered(enabled: boolean) {
  return useQuery({
    queryKey: ['filtered-items'],
    enabled,
    queryFn: async () =>
      filteredBySource(
        await fetchAllPages<FilteredRow>(
          async (from, to) =>
            await supabase
              .from('filtered_item')
              .select('source_id,title,reason,last_seen_at')
              .order('last_seen_at', { ascending: false })
              .range(from, to),
        ),
      ),
  });
}
