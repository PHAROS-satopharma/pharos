import { describe, expect, it } from 'vitest';
import { distinctWords } from './words';

describe('distinctWords', () => {
  it('lists a word once, however many languages list it', () => {
    const quinsair = ['da', 'de', 'en', 'es', 'fi', 'fr', 'is', 'it', 'nb', 'nl', 'pt', 'sv'].map((lang) => ({
      text: 'QUINSAIR',
      lang,
    }));
    const words = distinctWords([
      { text: 'Levofloxacin', lang: 'de' },
      { text: 'Levofloxacin', lang: 'en' },
      { text: 'levofloxacin', lang: 'sv' },
      ...quinsair,
    ]);
    expect(words.map((w) => w.text)).toEqual(['Levofloxacin', 'QUINSAIR']);
    expect(words[0].langs).toEqual(['de', 'en', 'sv']);
    expect(words[1].langs).toHaveLength(12);
  });

  it('keeps the language of a word only one language lists, and a word with none', () => {
    expect(distinctWords([{ text: 'ofloxacin', lang: 'en' }, { text: 'Tavanic', lang: null }])).toEqual([
      { text: 'ofloxacin', langs: ['en'] },
      { text: 'Tavanic', langs: [] },
    ]);
  });
});
