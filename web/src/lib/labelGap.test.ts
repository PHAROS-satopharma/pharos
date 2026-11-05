import { describe, expect, it } from 'vitest';
import { addedSentences, compareWithOurs, euSection, sameLanguage, splitSections } from './labelGap';

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
});

describe('the gap check', () => {
  it('finds the sentences the originator added', () => {
    expect(
      addedSentences(
        'Use with caution in renal impairment.',
        'Use with caution in renal impairment. Cases of acute kidney injury have been reported.',
      ),
    ).toEqual(['Cases of acute kidney injury have been reported.']);
  });
  it('says covered, partly covered or missing against our section', () => {
    const ours = 'Use with caution in patients with renal impairment. Cases of acute kidney injury have been reported rarely.';
    const [covered, partly, missing] = compareWithOurs(
      [
        'Cases of acute kidney injury have been reported.',
        'Use with caution in renal impairment and hepatic failure.',
        'Drug reaction with eosinophilia and systemic symptoms (DRESS) can occur.',
      ],
      ours,
    );
    expect(covered.status).toBe('covered');
    expect(partly.status).toBe('partly');
    expect(missing.status).toBe('missing');
    expect(missing.closest).toBeNull();
  });
  it('maps US and Japanese sections to the SmPC section', () => {
    expect(euSection('us:adverse_reactions')).toBe('4.8');
    expect(euSection('ja:2')).toBe('4.3');
    expect(euSection('4.4')).toBe('4.4');
    expect(euSection('us:unknown')).toBeNull();
  });
  it('treats en and en-GB as one language', () => {
    expect(sameLanguage('en', 'en-GB')).toBe(true);
    expect(sameLanguage('en', 'fr')).toBe(false);
  });
});
