import { describe, expect, it } from 'vitest';
import { alreadyWatched } from './alreadyWatched';

const atc = new Set(['C07AG02']);
const names = new Set(['carvedilol', 'ivy leaf']);

describe('alreadyWatched', () => {
  it('knows an ingredient with no ATC code by its name (Ivy leaf, 11 November 2026)', () => {
    expect(alreadyWatched({ inn_en: 'Ivy leaf', atc_code: null }, atc, names)).toBe(true);
    expect(alreadyWatched({ inn_en: ' Ivy Leaf ', atc_code: null }, atc, names)).toBe(true);
    expect(alreadyWatched({ inn_en: 'Thyme', atc_code: null }, atc, names)).toBe(false);
  });

  it('knows an ingredient with an ATC code by the code only', () => {
    expect(alreadyWatched({ inn_en: 'Coreg', atc_code: 'C07AG02' }, atc, names)).toBe(true);
    expect(alreadyWatched({ inn_en: 'carvedilol', atc_code: 'C07AG99' }, atc, names)).toBe(false);
  });
});
