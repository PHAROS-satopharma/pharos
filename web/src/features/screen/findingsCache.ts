// Where the screen holds the five-day clock and the signal of a notice (finding_state), and how a change reaches
// every copy of it. The cache is written here, never read through a second observer: a second useQuery on the
// same key with no queryFn would take over the query's options and break the reload after a refusal.

import type { QueryClient } from '@tanstack/react-query';
import type { WithFindings } from './clock';
import type { IngredientScreenData, PaperPage } from './types';

/** A change to the clock or the signal of one notice; it leaves everything else as it was. */
export type FindingsPatch = <T extends WithFindings>(data: T) => T;

/**
 * Writes the change where the screen holds the notice: its data under `queryKey` (the notices of its mentions) and,
 * for a paper, every page of papers under `papersKey` (the notices of the papers). A copy that does not hold the
 * notice is left as it was.
 */
export function patchFindings(
  qc: QueryClient,
  queryKey: readonly unknown[],
  papersKey: readonly unknown[] | undefined,
  fn: FindingsPatch,
): void {
  qc.setQueryData<IngredientScreenData>(queryKey, (old) => (old ? fn(old) : old));
  if (papersKey) qc.setQueriesData<PaperPage>({ queryKey: papersKey }, (old) => (old ? fn(old) : old));
}

/** After a refusal (the notice or its signal changed meanwhile): the screen, and the papers' pages, read again. */
export function reloadFindings(qc: QueryClient, queryKey: readonly unknown[], papersKey: readonly unknown[] | undefined): void {
  void qc.invalidateQueries({ queryKey });
  if (papersKey) void qc.invalidateQueries({ queryKey: papersKey });
}

/** Other ranges and screens read again when next opened; this one shows the change now. */
export function staleElsewhere(qc: QueryClient, papersKey: readonly unknown[] | undefined): void {
  void qc.invalidateQueries({ queryKey: ['ingredient-screen'], refetchType: 'none' });
  // the papers' pages of every range (the key's first part names them all)
  if (papersKey) void qc.invalidateQueries({ queryKey: papersKey.slice(0, 1), refetchType: 'none' });
}
