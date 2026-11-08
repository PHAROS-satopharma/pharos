/** What remove_ingredient (0100) answers. */
export interface RemoveIngredientResult {
  outcome: 'deleted' | 'paused';
  name: string;
  reasons: string[];
}

/** The answer in her words: "Deleted carvedilolx." or "Kept and paused: Carvedilol has 3 notices linked to it and a
 *  product: Carvexa." */
export function removedIngredientText(r: RemoveIngredientResult): string {
  if (r.outcome === 'deleted') return `Deleted ${r.name}.`;
  const why = r.reasons.length > 1 ? `${r.reasons.slice(0, -1).join(', ')} and ${r.reasons.at(-1)}` : (r.reasons[0] ?? '');
  return `Kept and paused: ${r.name} has ${why}. It is no longer looked for; switch Watched back on to look for it again.`;
}
