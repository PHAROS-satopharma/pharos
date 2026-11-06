import { describe, expect, it } from 'vitest';
import {
  currentJapanCodes,
  japanCodeOf,
  japanCodesOf,
  localTerms,
  pmdaGeneralListUrl,
  sameJapanCodes,
} from './japanCode';

// Levofloxacin hydrate's PMDA 一般名 code is 6241013: https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/6241013
// lists Cravit and its generics. Never fetched here.
const term = (over: Partial<{ kind: string; country_code: string | null; term: string; lang: string }>) => ({
  kind: 'inn',
  country_code: null,
  term: 'levofloxacin',
  lang: 'en',
  ...over,
});

describe('the Japan code typed for an ingredient (set_japan_code, 0052)', () => {
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

  it('reads the current codes from the ingredient’s terms: kind code, Japan only, in order', () => {
    expect(currentJapanCodes([term({})])).toEqual([]);
    expect(currentJapanCodes([term({ kind: 'code', country_code: null, term: '6241013' })])).toEqual([]);
    expect(currentJapanCodes([term({ kind: 'brand', country_code: 'JP', term: 'クラビット', lang: 'ja' })])).toEqual([]);
    expect(
      currentJapanCodes([term({}), term({ kind: 'code', country_code: 'JP', term: '6241013', lang: 'ja' })]),
    ).toEqual(['6241013']);
    expect(
      currentJapanCodes([
        term({ kind: 'code', country_code: 'JP', term: '1141700', lang: 'ja' }),
        term({ kind: 'code', country_code: 'JP', term: '1141007', lang: 'ja' }),
      ]),
    ).toEqual(['1141007', '1141700']);
  });

  it('opens the PMDA page that lists the products under the code', () => {
    expect(pmdaGeneralListUrl('6241013')).toBe('https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/6241013');
  });
});

// Paracetamol (アセトアミノフェン): PMDA files the tablets under 1141007, the suppositories under 1141700 and the
// injection under 1141400 (GeneralList pages read 6 Nov 2026), so one ingredient needs several codes (0069).
describe('several Japan codes in one field (set_japan_codes, 0069)', () => {
  it('reads every code typed, separated by commas, spaces, new lines or Japanese commas', () => {
    expect(japanCodesOf('1141007, 1141700')).toEqual({ codes: ['1141007', '1141700'], wrong: [] });
    expect(japanCodesOf(' 1141007 1141700
1141400 ')).toEqual({ codes: ['1141007', '1141700', '1141400'], wrong: [] });
    expect(japanCodesOf('1141007、1141700;1141400')).toEqual({
      codes: ['1141007', '1141700', '1141400'],
      wrong: [],
    });
    expect(japanCodesOf('6241013')).toEqual({ codes: ['6241013'], wrong: [] });
  });

  it('stores a YJ code as its 7 characters and a repeated code once', () => {
    expect(japanCodesOf('1141007F1063, 1141007, 1141700j1029')).toEqual({ codes: ['1141007', '1141700'], wrong: [] });
  });

  it('names what is not a Japan code, and keeps the good ones', () => {
    expect(japanCodesOf('1141007, N02BE01, 114100')).toEqual({ codes: ['1141007'], wrong: ['N02BE01', '114100'] });
    expect(japanCodesOf('')).toEqual({ codes: [], wrong: [] });
    expect(japanCodesOf(' , ')).toEqual({ codes: [], wrong: [] });
  });

  it('tells whether the codes typed are the ones saved, whatever their order', () => {
    expect(sameJapanCodes(['1141700', '1141007'], ['1141007', '1141700'])).toBe(true);
    expect(sameJapanCodes(['1141007'], ['1141007', '1141700'])).toBe(false);
    expect(sameJapanCodes([], [])).toBe(true);
  });
});

describe('the Local codes column (localTerms)', () => {
  const nameOf = (c: string) => ({ JP: 'Japan', KR: 'South Korea' })[c] ?? c;

  it('shows the Japan code as a code, with its country, and leaves out names used in every country', () => {
    expect(localTerms([term({}), term({ kind: 'code', country_code: 'JP', term: '6241013' })], nameOf)).toEqual([
      { term: '6241013', isCode: true, where: 'Japan' },
    ]);
  });

  it('keeps a name that is used in one country only as a name', () => {
    expect(localTerms([term({ kind: 'brand', country_code: 'KR', term: '크라비트' })], nameOf)).toEqual([
      { term: '크라비트', isCode: false, where: 'South Korea' },
    ]);
  });

  it('is empty when every name is looked for everywhere', () => {
    expect(localTerms([term({}), term({ lang: 'fr', term: 'lévofloxacine' })], nameOf)).toEqual([]);
  });
});
