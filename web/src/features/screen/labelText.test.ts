import { describe, expect, it } from 'vitest';
import { normalize, sectionOrder, splitSections } from './labelText';

const LEAFLET = `SUMMARY OF PRODUCT CHARACTERISTICS
1. NAME OF THE MEDICINAL PRODUCT
Lornox 8 mg film-coated tablets
4. CLINICAL PARTICULARS
4.1 Therapeutic indications
Short-term relief of acute mild to moderate pain.
4.4 Special warnings and precautions for use
Use with caution in patients with renal impairment.
1. Monitor renal function in the elderly.
4.8 Undesirable effects
Nausea, dyspepsia and abdominal pain are common.
4.8.1 Tabulated list
Headache is uncommon.
5. PHARMACOLOGICAL PROPERTIES
5.1 Pharmacodynamic properties
NSAID.`;

describe('splitSections', () => {
  it('finds the numbered sections, keeps a numbered list and third-level headings inside them', () => {
    const s = splitSections(LEAFLET);
    // "4" and "5" are headings with no text of their own before 4.1 and 5.1, so they are left out.
    expect(Object.keys(s)).toEqual(['1', '4.1', '4.4', '4.8', '5.1']);
    expect(s['4.4']).toBe('Use with caution in patients with renal impairment. 1. Monitor renal function in the elderly.');
    expect(s['4.8']).toContain('Headache is uncommon.');
  });
  it('reads Windows line ends; a number that is no section number stays in the text', () => {
    const s = splitSections('4.4 Warnings\r\nText.\r\n2.5 mg a day is the ceiling.\r\n4.8 Effects\r\nNausea.');
    expect(Object.keys(s)).toEqual(['4.4', '4.8']);
    expect(s['4.4']).toBe('Text. 2.5 mg a day is the ceiling.');
  });
  it('gives nothing for text without numbered sections', () => {
    expect(splitSections('Just a paragraph of text.')).toEqual({});
  });
});

describe('normalize', () => {
  it('joins hyphenation at line ends and squeezes whitespace', () => {
    expect(normalize('renal impair-\nment  here now')).toBe('renal impairment here now');
  });
});

describe('sectionOrder', () => {
  it('sorts section numbers numerically', () => {
    expect(['4.8', '10', '4.1', '1', '4.4'].sort(sectionOrder)).toEqual(['1', '4.1', '4.4', '4.8', '10']);
  });
});
