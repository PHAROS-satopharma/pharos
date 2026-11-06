import { describe, expect, it } from 'vitest';
import { profileMode, profileWords, switchesFor, type LinkedClass } from './searchProfile';

const group: LinkedClass = {
  cls: {
    name_en: 'Fluoroquinolones',
    class_term: [
      { term: 'fluoroquinolone', lang: 'en', mode: 'stem' },
      { term: 'Fluorchinolon', lang: 'de', mode: 'stem' },
    ],
  },
  link: { relation: 'group', enabled: true },
};
const parent: LinkedClass = {
  cls: {
    name_en: 'Quinolone antibacterials',
    class_term: [
      { term: 'quinolone antibiotic', lang: 'en', mode: 'stem' },
      { term: 'Fluoroquinolone', lang: 'en', mode: 'stem' },
      { term: 'ニューキノロン', lang: 'ja', mode: 'substring' },
    ],
  },
  link: { relation: 'parent', enabled: false },
};
const names = [
  { term: 'levofloxacin', lang: 'en', mode: 'stem' as const },
  { term: 'Levofloxacin', lang: 'de', mode: 'stem' as const },
];

describe('the search profile', () => {
  it('is derived from the switches', () => {
    expect(profileMode([])).toBe('ingredient');
    expect(profileMode([{ enabled: false }, { enabled: false }])).toBe('ingredient');
    expect(profileMode([{ enabled: true }, { enabled: true }])).toBe('ingredient_groups');
    expect(profileMode([{ enabled: true }, { enabled: false }])).toBe('custom');
  });

  it('knows which switches to change for a mode', () => {
    const links = [
      { class_id: 'g', enabled: true },
      { class_id: 'p', enabled: false },
    ];
    expect(switchesFor('ingredient', links)).toEqual([{ class_id: 'g', enabled: false }]);
    expect(switchesFor('ingredient_groups', links)).toEqual([{ class_id: 'p', enabled: true }]);
    expect(switchesFor('ingredient_groups', [{ class_id: 'g', enabled: true }])).toEqual([]);
  });

  it('lists the names first, then the words of the classes that are on, once per language', () => {
    const words = profileWords(names, [group, parent]);
    expect(words.map((w) => `${w.lang}:${w.term}:${w.kind}`)).toEqual([
      'en:levofloxacin:name',
      'de:Levofloxacin:name',
      'en:fluoroquinolone:group',
      'de:Fluorchinolon:group',
    ]);
    expect(words[2].from).toBe('Fluoroquinolones');
    expect(words[0].from).toBeNull();
  });

  it('adds the parent class only once it is switched on, without repeating a word', () => {
    const on: LinkedClass = { ...parent, link: { relation: 'parent', enabled: true } };
    const words = profileWords(names, [group, on]);
    expect(words.map((w) => `${w.lang}:${w.term}`)).toEqual([
      'en:levofloxacin',
      'de:Levofloxacin',
      'en:fluoroquinolone',
      'de:Fluorchinolon',
      'en:quinolone antibiotic',
      'ja:ニューキノロン',
    ]);
    expect(words.filter((w) => w.kind === 'parent').map((w) => w.from)).toEqual([
      'Quinolone antibacterials',
      'Quinolone antibacterials',
    ]);
  });
});
