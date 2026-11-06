import { describe, expect, it } from 'vitest';
import { classesOf, className, isDue, wordsByLanguage, wordsSummary, type DrugClass } from './drugClasses';

const fq: DrugClass = {
  id: 'c1',
  code: 'J01MA',
  name_en: 'Fluoroquinolones',
  origin: 'atc',
  confirmed_by: null,
  confirmed_at: null,
  class_term: [],
  ingredient_class: [{ ingredient_id: 'levo' }],
};

describe('the drug class line', () => {
  it('names an ATC class with its code, a hand-made class by its name', () => {
    expect(className(fq)).toBe('Fluoroquinolones (J01MA)');
    expect(className({ name_en: 'Non-steroidal anti-inflammatory drugs', code: 'NSAID', origin: 'hand' })).toBe(
      'Non-steroidal anti-inflammatory drugs',
    );
  });

  it('counts the words and their languages in plain words', () => {
    expect(wordsSummary([])).toBe('no words yet');
    expect(wordsSummary([{ lang: 'en' }])).toBe('1 word in 1 language');
    expect(wordsSummary([{ lang: 'en' }, { lang: 'en' }, { lang: 'sv' }])).toBe('3 words in 2 languages');
  });

  it('knows when a word still waits for the check of the past', () => {
    expect(isDue({ changed_at: '2026-11-06T10:00:00Z', rematched_at: null })).toBe(true);
    expect(isDue({ changed_at: '2026-11-06T10:00:00Z', rematched_at: '2026-11-06T09:00:00Z' })).toBe(true);
    expect(isDue({ changed_at: '2026-11-06T10:00:00Z', rematched_at: '2026-11-06T10:00:00Z' })).toBe(false);
  });

  it('groups the words by language name, then alphabetically', () => {
    const groups = wordsByLanguage([
      { lang: 'sv', term: 'Fluorokinolon' },
      { lang: 'en', term: 'fluroquinolone' },
      { lang: 'en', term: 'fluoroquinolone' },
      { lang: 'de', term: 'Fluorchinolon' },
    ]);
    expect(groups.map(([l]) => l)).toEqual(['en', 'de', 'sv']); // English, German, Swedish
    expect(groups[0][1].map((t) => t.term)).toEqual(['fluoroquinolone', 'fluroquinolone']);
  });

  it('finds the classes an ingredient belongs to', () => {
    expect(classesOf('levo', [fq])).toEqual([fq]);
    expect(classesOf('lorno', [fq])).toEqual([]);
  });
});
