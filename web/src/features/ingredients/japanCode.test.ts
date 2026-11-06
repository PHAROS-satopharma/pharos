import { describe, expect, it } from 'vitest';
import { currentJapanCode, japanCodeOf, pmdaGeneralListUrl } from './japanCode';

// Levofloxacin hydrate's PMDA 一般名 code is 6241013: https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/6241013
// lists Cravit and its generics. Never fetched here.
const term = (over: Partial<{ kind: string; country_code: string | null; term: string; lang: string }>) => ({
  kind: 'inn',
  country_code: null,
  term: 'levofloxacin',
  lang: 'en',
  ...over,
});

describe('the Japan code typed for an ingredient (set_japan_code, 0051)', () => {
  it('stores the 7-character code, from the code itself or from the 12-character YJ code', () => {
    expect(japanCodeOf('6241013')).toBe('6241013');
    expect(japanCodeOf(' 6241013 ')).toBe('6241013');
    expect(japanCodeOf('6241013F1020')).toBe('6241013');
    expect(japanCodeOf('6241013f1020')).toBe('6241013');
    expect(japanCodeOf('114903A')).toBe('114903A');
  });

  it('refuses what is not a Japan code, as the database does', () => {
    expect(japanCodeOf('')).toBeNull();
    expect(japanCodeOf('J01MA12')).toBeNull();
    expect(japanCodeOf('624101')).toBeNull();
    expect(japanCodeOf('62410130')).toBeNull();
    expect(japanCodeOf('6241013F102')).toBeNull();
  });

  it('reads the current code from the ingredient’s terms: kind code, Japan only', () => {
    expect(currentJapanCode([term({})])).toBeNull();
    expect(currentJapanCode([term({ kind: 'code', country_code: null, term: '6241013' })])).toBeNull();
    expect(currentJapanCode([term({ kind: 'brand', country_code: 'JP', term: 'クラビット', lang: 'ja' })])).toBeNull();
    expect(
      currentJapanCode([term({}), term({ kind: 'code', country_code: 'JP', term: '6241013', lang: 'ja' })]),
    ).toBe('6241013');
  });

  it('opens the PMDA page that lists the products under the code', () => {
    expect(pmdaGeneralListUrl('6241013')).toBe('https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/6241013');
  });
});
