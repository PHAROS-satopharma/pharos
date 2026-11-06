import { languageName } from '../../lib/labels';
import type { MatchMode } from '../../lib/types';

/** 'atc': made by the daily job from the ingredient's ATC code (level 4 or 3); 'hand': set by hand (the NSAID seed,
 * a group added on the Ingredients page). */
export type ClassOrigin = 'atc' | 'hand';

/**
 * What a class is to an ingredient (ingredient_class.relation, migration 0049): 'group' is its ATC level-4 group,
 * searched from the start; 'parent' the class above it, shown but switched off until an administrator has read its
 * words; 'manual' a group given by hand.
 */
export type ClassRelation = 'group' | 'parent' | 'manual';

export interface ClassLink {
  ingredient_id: string;
  relation: ClassRelation;
  /** Whether the class's words are looked for (notices, literature, the check of the past). */
  enabled: boolean;
}

export interface ClassTerm {
  id: string;
  lang: string;
  term: string;
  mode: MatchMode;
  source: string | null;
  changed_at: string;
  rematched_at: string | null;
}

export interface DrugClass {
  id: string;
  code: string;
  name_en: string;
  origin: ClassOrigin;
  confirmed_by: string | null;
  confirmed_at: string | null;
  class_term: ClassTerm[];
  ingredient_class: ClassLink[];
  /** Filled from person_directory: who confirmed the class. */
  confirmed_by_name?: string | null;
}

export const DRUG_CLASS_SELECT =
  'id,code,name_en,origin,confirmed_by,confirmed_at,' +
  'class_term(id,lang,term,mode,source,changed_at,rematched_at),ingredient_class(ingredient_id,relation,enabled)';

export const ORIGIN_LABEL: Record<ClassOrigin, string> = {
  atc: 'from the ATC code',
  hand: 'set by hand',
};

export const RELATION_LABEL: Record<ClassRelation, string> = {
  group: 'its group',
  parent: 'the class above its group',
  manual: 'a group added by hand',
};

/** The link between an ingredient and a class, or undefined when the class is not the ingredient's. */
export function linkOf(ingredientId: string, c: Pick<DrugClass, 'ingredient_class'>): ClassLink | undefined {
  return c.ingredient_class.find((l) => l.ingredient_id === ingredientId);
}

/** "Fluoroquinolones (J01MA)", or the name alone when the code is not an ATC code (NSAID). */
export function className(c: Pick<DrugClass, 'name_en' | 'code' | 'origin'>): string {
  return c.origin === 'atc' ? `${c.name_en} (${c.code})` : c.name_en;
}

/** "words in 12 languages", "1 word in 1 language", "no words yet". */
export function wordsSummary(terms: Pick<ClassTerm, 'lang'>[]): string {
  if (terms.length === 0) return 'no words yet';
  const langs = new Set(terms.map((t) => t.lang)).size;
  return `${terms.length === 1 ? '1 word' : `${terms.length} words`} in ${langs === 1 ? '1 language' : `${langs} languages`}`;
}

/** A word saved since the stored notices were last checked with it: the next daily run checks the past again. */
export function isDue(t: Pick<ClassTerm, 'changed_at' | 'rematched_at'>): boolean {
  return t.rematched_at === null || new Date(t.rematched_at).getTime() < new Date(t.changed_at).getTime();
}

/** The words by language, languages in alphabetical order of their English name, words alphabetically. */
export function wordsByLanguage<T extends Pick<ClassTerm, 'lang' | 'term'>>(terms: T[]): [string, T[]][] {
  const by = new Map<string, T[]>();
  for (const t of terms) by.set(t.lang, [...(by.get(t.lang) ?? []), t]);
  return [...by.entries()]
    .sort(([a], [b]) => languageName(a).localeCompare(languageName(b)))
    .map(([lang, list]) => [lang, [...list].sort((x, y) => x.term.localeCompare(y.term, lang))]);
}

/** The classes an ingredient belongs to. */
export function classesOf(ingredientId: string, classes: DrugClass[]): DrugClass[] {
  return classes.filter((c) => c.ingredient_class.some((l) => l.ingredient_id === ingredientId));
}
