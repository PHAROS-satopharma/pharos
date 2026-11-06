import { useQuery } from '@tanstack/react-query';
import { invoke } from '../../lib/api';
import { literatureSearchKey, rangeProblem } from './literatureRange';
import type { LiteratureSearchResult } from './types';

/**
 * Live PubMed and PubMed Central counts for one ingredient and a range of publication dates (both days
 * included), with the links that open the same searches on the NCBI websites. Asks only for a valid range;
 * the function itself waits out NCBI's passing errors, so a failure is not retried here.
 */
export function useLiteratureSearch(ingredientId: string | null | undefined, from: string, to: string) {
  const ready = Boolean(ingredientId) && rangeProblem(from, to) === null;
  return useQuery({
    queryKey: literatureSearchKey(ingredientId ?? '', from, to),
    enabled: ready,
    staleTime: 10 * 60_000,
    retry: false,
    queryFn: () =>
      invoke<LiteratureSearchResult>('literature-search', { ingredient_id: ingredientId, from, to }),
  });
}
