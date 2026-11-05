import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { escapeLike, unwrap } from '../../lib/api';
import type { DocType, IssueRow, IssueStatus } from '../../lib/types';
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

/** The API returns at most 1,000 rows per request, so longer lists are read in pages of this size. */
const API_PAGE = 1000;

/** The Excel export stops here; the screen then says how many matched. */
export const EXPORT_CAP = 20000;

/**
 * The first `limit` rows that match the filters, read in pages of at most 1,000, and how many match in all
 * (counted on the first page).
 */
async function readIssues(f: IssueFilters, limit: number): Promise<{ rows: IssueRow[]; total: number }> {
  const rows: IssueRow[] = [];
  let total = 0;
  for (let from = 0; from < limit; from += API_PAGE) {
    const to = Math.min(from + API_PAGE, limit) - 1;
    const res = await issueQuery(f, from === 0).range(from, to);
    const page = unwrap<IssueRow[] | null>(res) ?? [];
    if (from === 0) total = res.count ?? page.length;
    rows.push(...page);
    if (page.length < to - from + 1) break;
  }
  return { rows, total: Math.max(total, rows.length) };
}

export function useIssues(f: IssueFilters, limit: number) {
  return useQuery({
    queryKey: ['issues', f, limit],
    placeholderData: keepPreviousData,
    queryFn: () => readIssues(f, limit),
  });
}

/**
 * Every row that matches the filters, up to EXPORT_CAP, for the Excel export. `total` is how many match in
 * all, so the caller can say when the file holds only the first EXPORT_CAP.
 */
export function fetchAllIssues(f: IssueFilters): Promise<{ rows: IssueRow[]; total: number }> {
  return readIssues(f, EXPORT_CAP);
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
