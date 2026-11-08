import { describe, expect, it } from 'vitest';
import { removedIngredientText } from './removeIngredient';

describe('removedIngredientText', () => {
  it('says a deleted ingredient is gone', () => {
    expect(removedIngredientText({ outcome: 'deleted', name: 'carvedilolx', reasons: [] })).toBe('Deleted carvedilolx.');
  });

  it('says why a paused ingredient was kept', () => {
    expect(
      removedIngredientText({
        outcome: 'paused',
        name: 'carvedilol',
        reasons: ['3 notices linked to it', 'a signal', 'a product: Carvexa'],
      }),
    ).toBe(
      'Kept and paused: carvedilol has 3 notices linked to it, a signal and a product: Carvexa. ' +
        'It is no longer looked for; switch Watched back on to look for it again.',
    );
    expect(removedIngredientText({ outcome: 'paused', name: 'x', reasons: ['its label watch'] })).toContain(
      'x has its label watch.',
    );
  });
});
