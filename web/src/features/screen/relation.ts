// How a mention was found (migration 0049): by the ingredient's own name, by its group, by a group added by
// hand, or by the class above its group, which is only a possibly relevant class-level signal to assess.

import type { Mention, ScreenClass } from './types';

/** The tag on a mention found by a class word; null when the ingredient's own name matched. */
export function relationTag(m: Pick<Mention, 'by_class' | 'relation' | 'class_name'>): { text: string; title: string } | null {
  if (!m.by_class || m.relation === 'name') return null;
  const name = m.class_name ?? 'its class';
  if (m.relation === 'parent') {
    return {
      text: `Related class: ${name} · assess`,
      title: 'Only a word of the class above its group matched: a class-level signal that may concern it, to be assessed',
    };
  }
  if (m.relation === 'manual') {
    return { text: `Group (by hand): ${name}`, title: 'Only a word of a group added by hand matched, not the ingredient’s own names' };
  }
  return { text: `Group: ${name}`, title: 'Only a word of its drug class matched, not the ingredient’s own names' };
}

/**
 * "Fluoroquinolones, NSAID (notices only), Quinolone antibacterials (off)": the classes in the head of the screen.
 * A class kept out of the literature search (0051) is marked notices only.
 */
export function classesLine(
  classes: (Pick<ScreenClass, 'name_en' | 'enabled'> & Partial<Pick<ScreenClass, 'literature'>>)[],
): string | null {
  if (classes.length === 0) return null;
  return classes
    .map((c) =>
      !c.enabled ? `${c.name_en} (off)` : c.literature === false ? `${c.name_en} (notices only)` : c.name_en,
    )
    .join(', ');
}
