// The words that matched a notice, each once. Pure helper, no I/O.

import type { MatchedWord } from './types';

export interface DistinctWord {
  text: string;
  /** Every language that lists this word, in the order first met. */
  langs: string[];
}

/** Each matched word once, however many languages list it (Quinsair is one word in twelve languages). */
export function distinctWords(terms: MatchedWord[]): DistinctWord[] {
  const words = new Map<string, DistinctWord>();
  for (const t of terms) {
    const key = t.text.toLocaleLowerCase();
    const word = words.get(key) ?? { text: t.text, langs: [] };
    if (t.lang && !word.langs.includes(t.lang)) word.langs.push(t.lang);
    words.set(key, word);
  }
  return [...words.values()];
}
