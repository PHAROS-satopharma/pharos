import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { escapeLike, fetchAllPages, unwrap } from '../../lib/api';
import { ISSUE_STATUSES, type DocType, type IssueRow, type IssueStatus } from '../../lib/types';
import { DOC_TYPE_LABEL, STATUS_LABEL } from '../../lib/labels';

export interface IssueFilters {
  country: string;
  ingredient: string;
  status: IssueStatus | '';
  type: DocType | '';
  q: string;
  history: boolean;
  classWide: boolean;
}

export const ISSUE_COLUMNS =
  'id,first_date,doc_type,title,status,class_only,is_backfill,link,anchor_country,anchor_regulator,countries,ingredients,copies';

function issueQuery(f: IssueFilters, withCount: boolean) {
  let q = supabase.from('v_issue_table').select(ISSUE_COLUMNS, withCount ? { count: 'exact' as const } : undefined);
  if (!f.history) q = q.eq('is_backfill', false);
  if (!f.classWide) q = q.eq('class_only', false);
  if (f.status) q = q.eq('status', f.status);
  if (f.type) q = q.eq('doc_type', f.type);
  if (f.country) q = q.contains('countries', [f.country]);
  if (f.ingredient) q = q.contains('ingredients', [f.ingredient]);
  const text = f.q.trim();
  if (text) q = q.ilike('title', `%${escapeLike(text)}%`);
  return q.order('first_date', { ascending: false, nullsFirst: false }).order('id', { ascending: false });
}

export function useIssues(f: IssueFilters, limit: number) {
  return useQuery({
    queryKey: ['issues', f, limit],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const res = await issueQuery(f, true).range(0, limit - 1);
      const rows = unwrap<IssueRow[] | null>(res) ?? [];
      return { rows, total: res.count ?? rows.length };
    },
  });
}

/**
 * How many notifications of each status match every filter except the status: the figures in the masthead.
 * One count-only request per status. The key sits under 'issues' so a recorded decision refreshes it too.
 */
export function useStatusCounts(f: IssueFilters) {
  const base: IssueFilters = { ...f, status: '' };
  return useQuery({
    queryKey: ['issues', 'status-counts', base],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const pairs = await Promise.all(
        ISSUE_STATUSES.map(async (status) => {
          let q = supabase.from('v_issue_table').select('id', { count: 'exact', head: true }).eq('status', status);
          if (!base.history) q = q.eq('is_backfill', false);
          if (!base.classWide) q = q.eq('class_only', false);
          if (base.type) q = q.eq('doc_type', base.type);
          if (base.country) q = q.contains('countries', [base.country]);
          if (base.ingredient) q = q.contains('ingredients', [base.ingredient]);
          const text = base.q.trim();
          if (text) q = q.ilike('title', `%${escapeLike(text)}%`);
          const res = await q;
          unwrap<null>(res);
          return [status, res.count ?? 0] as const;
        }),
      );
      return Object.fromEntries(pairs) as Record<IssueStatus, number>;
    },
  });
}

/** Every row that matches the filters, for the Excel export. */
export function fetchAllIssues(f: IssueFilters): Promise<IssueRow[]> {
  return fetchAllPages<IssueRow>(async (from, to) => await issueQuery(f, false).range(from, to), 1000, 20000);
}

export function describeFilters(f: IssueFilters): string {
  const parts: string[] = [];
  if (f.country) parts.push(`country ${f.country}`);
  if (f.ingredient) parts.push(`ingredient ${f.ingredient}`);
  if (f.status) parts.push(`status ${STATUS_LABEL[f.status]}`);
  if (f.type) parts.push(`type ${DOC_TYPE_LABEL[f.type]}`);
  if (f.q.trim()) parts.push(`title contains “${f.q.trim()}”`);
  parts.push(f.history ? 'history included' : 'history left out');
  parts.push(f.classWide ? 'class-wide notices included' : 'class-wide notices left out');
  return parts.join('; ');
}

export function useIngredientNames() {
  return useQuery({
    queryKey: ['ingredient-names'],
    staleTime: 5 * 60_000,
    queryFn: async () =>
      (unwrap<{ inn_en: string }[] | null>(await supabase.from('ingredient').select('inn_en').order('inn_en')) ?? []).map(
        (r) => r.inn_en,
      ),
  });
}
