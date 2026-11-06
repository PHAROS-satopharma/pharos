import { describe, expect, it } from 'vitest';
import type { IngredientTerm } from '../../lib/types';
import { draftsOf, isEmptyPlan, planTermEdit } from './editTerms';

function term(id: string, lang: string, word: string, extra: Partial<IngredientTerm> = {}): IngredientTerm {
  return {
    id,
    ingredient_id: 'ing',
    lang,
    country_code: null,
    term: word,
    kind: 'inn',
    mode: 'stem',
    exclusions: [],
    source: 'wikidata',
    verified_by: null,
    verified_at: null,
    ...extra,
  };
}

const saved = [
  term('a', 'en', 'levofloxacin'),
  term('b', 'fr', 'lévofloxacine'),
  term('c', 'es', 'Tavanic', { kind: 'brand', country_code: 'ES' }),
  term('jp', 'ja', '6241013', { kind: 'code', country_code: 'JP', mode: 'exact', source: 'pmda' }),
];

describe('draftsOf', () => {
  it('keeps every name with its row id and leaves the Japan code out', () => {
    const d = draftsOf(saved);
    expect(d.map((x) => x.uid)).toEqual(['a', 'b', 'c']);
    expect(d[2]).toMatchObject({ country: 'ES', kind: 'brand', exclusions: '' });
  });
});

describe('planTermEdit', () => {
  it('writes nothing when nothing changed', () => {
    expect(isEmptyPlan(planTermEdit(saved, draftsOf(saved)))).toBe(true);
  });

  it('updates a changed name, removes an emptied or dropped one, inserts a new one, never the Japan code', () => {
    const d = draftsOf(saved);
    d[0] = { ...d[0], term: ' levofloxacine ', exclusions: 'ofloxacin, ' };
    d[1] = { ...d[1], term: '  ' };
    const drafts = [d[0], d[1], { ...d[2], uid: 'new1', term: 'Cravit', country: '' }];
    const p = planTermEdit(saved, drafts);
    expect(p.remove.sort()).toEqual(['b', 'c']);
    expect(p.update).toEqual([
      {
        id: 'a',
        row: { lang: 'en', country_code: null, term: 'levofloxacine', kind: 'inn', mode: 'stem', exclusions: ['ofloxacin'] },
      },
    ]);
    expect(p.insert).toEqual([
      { lang: 'es', country_code: null, term: 'Cravit', kind: 'brand', mode: 'stem', exclusions: [], source: 'wikidata' },
    ]);
    expect(p.remove).not.toContain('jp');
  });

  it('refuses one word twice in one language', () => {
    const d = draftsOf(saved);
    d.push({ ...d[0], uid: 'new2' });
    expect(() => planTermEdit(saved, d)).toThrow(/twice/);
  });
});
