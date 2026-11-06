// What paper_state() and mlm_monitored() (migration 0044) say of the papers on the screen.

import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { chunk } from './papers';
import { PAPER_PAGE } from './queries';
import type { Paper, PaperStates } from './types';

export function paperStateKey(ingredientId: string, from: string, to: string): readonly unknown[] {
  return ['paper-state', ingredientId, from, to] as const;
}

/**
 * The state of every paper shown, asked 50 papers at a time (the pages the screen loads them in), so a
 * "Show more" asks only for the new page. Papers whose answer has not arrived yet are simply not in the map.
 */
export function usePaperStates(ingredientId: string, from: string, to: string, papers: Paper[]) {
  const pages = useMemo(() => chunk(papers.map((p) => p.document_id), PAPER_PAGE), [papers]);
  const results = useQueries({
    queries: pages.map((ids, index) => ({
      queryKey: [...paperStateKey(ingredientId, from, to), index],
      staleTime: 5 * 60_000,
      queryFn: async () => unwrap<PaperStates | null>(await supabase.rpc('paper_state', { p_documents: ids })) ?? {},
    })),
  });
  const states = useMemo(() => {
    const out: PaperStates = {};
    for (const r of results) if (r.data) Object.assign(out, r.data);
    return out;
  }, [results]);
  const error = results.find((r) => r.isError)?.error ?? null;
  return { states, error };
}

/** Whether EMA's literature monitoring list names the ingredient; undefined until the answer arrives. */
export function useMlmMonitored(ingredientId: string) {
  return useQuery({
    queryKey: ['mlm-monitored', ingredientId],
    staleTime: 60 * 60_000,
    queryFn: async () => unwrap<boolean>(await supabase.rpc('mlm_monitored', { p_ingredient: ingredientId })),
  });
}
