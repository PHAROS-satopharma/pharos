import { skipToken, useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { issueIdsOf } from './clock';
import type { Findings, IngredientScreenData, LabelChange, LabelChangesData, Mention, Paper } from './types';

/** Papers come 50 at a time: the screen's first 50, then ingredient_papers() for each "Show more". */
export const PAPER_PAGE = 50;

export function screenKey(ingredientId: string, from: string, to: string): readonly unknown[] {
  return ['ingredient-screen', ingredientId, from, to] as const;
}

export function labelChangesKey(ingredientId: string, from: string, to: string): readonly unknown[] {
  return ['label-changes', ingredientId, from, to] as const;
}

/** The notice of a label change as a Mention, so the decision buttons work on it as on any other mention. */
export function mentionOfChange(c: LabelChange): Mention {
  return {
    document_id: c.change_id,
    source_id: c.product.source_id,
    regulator_id: c.product.regulator_id,
    regulator_name: c.product.regulator_name,
    country_name: c.product.country_name,
    country_code: c.product.country_code,
    title: c.title,
    lang: c.lang,
    link: c.link,
    email_id: null,
    email_r2_key: null,
    date: c.detected_day,
    published_date: c.label_date,
    first_seen_at: c.detected_at,
    doc_type: 'label_change',
    terms: [],
    by_class: false,
    is_backfill: c.is_backfill,
    sections: c.sections,
    issue_id: c.issue_id,
    issue_status: c.issue_status,
    decision: c.decision,
  };
}

/** The label changes detected in the Cairo days (label_changes, 0043), with the five-day clock of their notices. */
export function useLabelChanges(ingredientId: string, from: string, to: string) {
  return useQuery({
    queryKey: labelChangesKey(ingredientId, from, to),
    enabled: Boolean(ingredientId),
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<LabelChangesData> => {
      const changes =
        unwrap<LabelChange[] | null>(
          await supabase.rpc('label_changes', { p_ingredient: ingredientId, p_from: from, p_to: to }),
        ) ?? [];
      const mentions = changes.map(mentionOfChange);
      const ids = [...new Set(mentions.map((m) => m.issue_id).filter((x): x is string => Boolean(x)))];
      const findings = ids.length
        ? (unwrap<Findings | null>(await supabase.rpc('finding_state', { p_issues: ids })) ?? {})
        : {};
      return { changes, regulators: [], label_changes: mentions, findings };
    },
  });
}

/** Everything the screen shows for one ingredient and a range of Cairo days (0039), with the five-day clock of
 *  every notice on it (finding_state, 0041). */
export function useIngredientScreen(ingredientId: string | undefined, from: string, to: string, enabled: boolean) {
  return useQuery({
    queryKey: screenKey(ingredientId ?? '', from, to),
    enabled: Boolean(ingredientId) && enabled,
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<IngredientScreenData> => {
      const screen = unwrap<Omit<IngredientScreenData, 'findings'>>(
        await supabase.rpc('ingredient_screen', { p_ingredient: ingredientId, p_from: from, p_to: to }),
      );
      const ids = issueIdsOf(screen);
      const findings = ids.length
        ? (unwrap<Findings | null>(await supabase.rpc('finding_state', { p_issues: ids })) ?? {})
        : {};
      return { ...screen, findings };
    },
  });
}

/** The screen's data as the cache holds it now, for a part of the screen that is given only the key. Never
 *  fetches: the screen itself does. */
export function useScreenData(queryKey: readonly unknown[]): IngredientScreenData | undefined {
  return useQuery<IngredientScreenData>({ queryKey, queryFn: skipToken }).data;
}

/** The papers after the first 50, in the screen's order, once she asks for more. */
export function useMorePapers(ingredientId: string, from: string, to: string, wanted: boolean) {
  return useInfiniteQuery({
    queryKey: ['ingredient-papers', ingredientId, from, to],
    enabled: wanted,
    staleTime: 5 * 60_000,
    initialPageParam: PAPER_PAGE,
    queryFn: async ({ pageParam }) =>
      unwrap<Paper[] | null>(
        await supabase
          .rpc('ingredient_papers', { p_ingredient: ingredientId, p_from: from, p_to: to })
          .order('by_class')
          .order('day', { ascending: false })
          .order('first_seen_at', { ascending: false })
          .order('document_id')
          .range(pageParam, pageParam + PAPER_PAGE - 1),
      ) ?? [],
    getNextPageParam: (last, _all, lastParam) => (last.length === PAPER_PAGE ? lastParam + PAPER_PAGE : undefined),
  });
}

export interface InboundEmail {
  subject: string | null;
  from_addr: string | null;
  received_at: string;
  text_body: string | null;
  html_body: string | null;
}

/** One e-mail of the mailbox, once she opens it. */
export function useInboundEmail(emailId: string | null, open: boolean) {
  return useQuery({
    queryKey: ['inbound-email', emailId],
    enabled: open && Boolean(emailId),
    queryFn: async () =>
      unwrap<InboundEmail | null>(
        await supabase
          .from('inbound_email')
          .select('subject,from_addr,received_at,text_body,html_body')
          .eq('id', emailId as string)
          .maybeSingle(),
      ),
  });
}
