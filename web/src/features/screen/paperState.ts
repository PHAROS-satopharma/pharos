// What paper_state() and mlm_monitored() (migration 0044) say of the papers on the screen, and finding_state()
// (0041, 0050, 0042) of the notices they are filed under.

import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { chunk, mergePaperPages, paperIssueIds } from './papers';
import { PAPER_PAGE } from './queries';
import type { Findings, Paper, PaperPage, PaperStates } from './types';

export function paperStateKey(ingredientId: string, from: string, to: string): readonly unknown[] {
  return ['paper-state', ingredientId, from, to] as const;
}

/**
 * The state of every paper shown, asked 50 papers at a time (the pages the screen loads them in), so a
 * "Show more" asks only for the new page. Each page also asks finding_state() for its papers' notices (at most
 * 50, one per paper), so a paper's notice has its five-day clock and its signal as a mention's has. The page is
 * the one place the screen holds them: DecisionButtons patches it after a decision, a report or a signal step.
 * Papers whose answer has not arrived yet are simply not in the maps.
 */
export function usePaperStates(ingredientId: string, from: string, to: string, papers: Paper[]) {
  const pages = useMemo(() => chunk(papers.map((p) => p.document_id), PAPER_PAGE), [papers]);
  const results = useQueries({
    queries: pages.map((ids, index) => ({
      queryKey: [...paperStateKey(ingredientId, from, to), index],
      staleTime: 5 * 60_000,
      queryFn: async (): Promise<PaperPage> => {
        const states =
          unwrap<PaperStates | null>(await supabase.rpc('paper_state', { p_documents: ids })) ?? {};
        const issues = paperIssueIds(states);
        const findings = issues.length
          ? (unwrap<Findings | null>(await supabase.rpc('finding_state', { p_issues: issues })) ?? {})
          : {};
        return { states, findings };
      },
    })),
  });
  const { states, findings } = useMemo(() => mergePaperPages(results.map((r) => r.data)), [results]);
  const error = results.find((r) => r.isError)?.error ?? null;
  return { states, findings, error };
}

/** Whether EMA's literature monitoring list names the ingredient; undefined until the answer arrives. */
export function useMlmMonitored(ingredientId: string) {
  return useQuery({
    queryKey: ['mlm-monitored', ingredientId],
    staleTime: 60 * 60_000,
    queryFn: async () => unwrap<boolean>(await supabase.rpc('mlm_monitored', { p_ingredient: ingredientId })),
  });
}
