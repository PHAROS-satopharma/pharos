import { describe, expect, it } from 'vitest';
import { classesLine, relationTag } from './relation';

describe('how a mention was found', () => {
  it('says nothing for the ingredient’s own name', () => {
    expect(relationTag({ by_class: false, relation: 'name', class_name: null })).toBeNull();
  });

  it('names the group, a group by hand, or the related class to assess', () => {
    expect(relationTag({ by_class: true, relation: 'group', class_name: 'Fluoroquinolones' })?.text).toBe(
      'Group: Fluoroquinolones',
    );
    expect(relationTag({ by_class: true, relation: 'manual', class_name: 'NSAID' })?.text).toBe('Group (by hand): NSAID');
    expect(relationTag({ by_class: true, relation: 'parent', class_name: 'Quinolone antibacterials' })?.text).toBe(
      'Related class: Quinolone antibacterials · assess',
    );
    expect(relationTag({ by_class: true, relation: 'group', class_name: null })?.text).toBe('Group: its class');
  });

  it('marks a class that is switched off in the head of the screen', () => {
    expect(classesLine([])).toBeNull();
    expect(
      classesLine([
        { name_en: 'Fluoroquinolones', enabled: true },
        { name_en: 'Quinolone antibacterials', enabled: false },
      ]),
    ).toBe('Fluoroquinolones, Quinolone antibacterials (off)');
  });

  it('marks a class kept out of the literature search as notices only', () => {
    expect(
      classesLine([
        { name_en: 'Oxicams', enabled: true, literature: true },
        { name_en: 'NSAID', enabled: true, literature: false },
        { name_en: 'M01A', enabled: false, literature: false },
      ]),
    ).toBe('Oxicams, NSAID (notices only), M01A (off)');
  });
});
