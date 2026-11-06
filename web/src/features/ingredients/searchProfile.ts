// The search profile of an ingredient (migration 0041): its own names plus the words of the classes whose
// switch is on. Pure functions; the switches themselves are ingredient_class.enabled, changed with
// set_class_search. Reusable by any screen that needs to say what PHAROS looks for.

import type { IngredientTerm, MatchMode } from '../../lib/types';
import type { ClassLink, ClassRelation, ClassTerm, DrugClass } from './drugClasses';

/** Derived from the switches, never stored. */
export type ProfileMode = 'ingredient' | 'ingredient_groups' | 'custom';

export const PROFILE_MODE_LABEL: Record<ProfileMode, string> = {
  ingredient: 'Ingredient only',
  ingredient_groups: 'Ingredient + groups',
  custom: 'Custom',
};

export const PROFILE_MODE_HINT: Record<ProfileMode, string> = {
  ingredient: 'Only its own names are looked for.',
  ingredient_groups: 'Its names and the words of every one of its classes are looked for.',
  custom: 'Some classes are searched and some are not; switch each one below.',
};

/** No class on (or no class at all) → ingredient only; every class on → ingredient + groups; some → custom. */
export function profileMode(links: Pick<ClassLink, 'enabled'>[]): ProfileMode {
  const on = links.filter((l) => l.enabled).length;
  if (on === 0) return 'ingredient';
  return on === links.length ? 'ingredient_groups' : 'custom';
}

/** The switches to change so that the profile reads `mode`; nothing for a mode already in place. */
export function switchesFor(
  mode: 'ingredient' | 'ingredient_groups',
  links: { class_id: string; enabled: boolean }[],
): { class_id: string; enabled: boolean }[] {
  const want = mode === 'ingredient_groups';
  return links.filter((l) => l.enabled !== want).map((l) => ({ class_id: l.class_id, enabled: want }));
}

/** Where a searched word comes from: the ingredient's own name, or a class by its relation. */
export type WordKind = 'name' | ClassRelation;

export const WORD_KIND_LABEL: Record<WordKind, string> = {
  name: 'Its name',
  group: 'Its group',
  parent: 'Related class',
  manual: 'Group by hand',
};

export interface ProfileWord {
  term: string;
  lang: string;
  mode: MatchMode;
  kind: WordKind;
  /** The class the word belongs to; null for the ingredient's own names. */
  from: string | null;
}

export interface LinkedClass {
  cls: Pick<DrugClass, 'name_en'> & { class_term: Pick<ClassTerm, 'term' | 'lang' | 'mode'>[] };
  link: Pick<ClassLink, 'relation' | 'enabled'>;
}

/**
 * Every word PHAROS looks for: the ingredient's names first, then the words of the classes that are switched
 * on, each word once per language (the first source keeps it). A class switched off adds nothing.
 */
export function profileWords(terms: Pick<IngredientTerm, 'term' | 'lang' | 'mode'>[], classes: LinkedClass[]): ProfileWord[] {
  const seen = new Set<string>();
  const out: ProfileWord[] = [];
  const add = (w: ProfileWord) => {
    const key = `${w.lang}|${w.term.trim().toLowerCase()}`;
    if (!w.term.trim() || seen.has(key)) return;
    seen.add(key);
    out.push(w);
  };
  for (const t of terms) add({ term: t.term, lang: t.lang, mode: t.mode, kind: 'name', from: null });
  for (const { cls, link } of classes) {
    if (!link.enabled) continue;
    for (const t of cls.class_term) add({ term: t.term, lang: t.lang, mode: t.mode, kind: link.relation, from: cls.name_en });
  }
  return out;
}
