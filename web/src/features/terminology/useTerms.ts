import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import type { TermConcept, TermHit, TermSource } from './terms';

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** term_search(): a code, or at least three letters (two for an exact name in a few scripts). */
export function useTermSearch(text: string, sources: TermSource[] | null, limit = 12) {
  const q = useDebounced(text.trim());
  return useQuery({
    queryKey: ['term-search', q, sources?.join(',') ?? 'all', limit],
    queryFn: async () =>
      unwrap<TermHit[]>(
        await supabase.rpc('term_search', { p_text: q, p_sources: sources && sources.length ? sources : null, p_limit: limit }),
      ),
    enabled: q.length >= 2,
    staleTime: 5 * 60_000,
  });
}

export async function lookupTerm(source: TermSource, code: string): Promise<TermConcept | null> {
  const rows = unwrap<TermConcept[]>(await supabase.rpc('term_lookup', { p_source: source, p_code: code }));
  return rows[0] ?? null;
}
