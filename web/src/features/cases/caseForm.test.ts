import { describe, expect, it } from 'vitest';
import { addDays, caseDue, caseMissing, clockLine, codingNorm, e2bProblems, numberOrNull, orNull, suggestionsFor, toBase64, type CaseForm } from './caseForm';

const FULL: CaseForm = {
  patient: { initials: 'A.M.', sex: 'female' },
  reporter: { qualification: 'physician' },
  products: [{ name: 'Casoxicam 8 mg', role: 'suspect' }],
  reactions: [{ verbatim: 'jaundice', meddra_llt_code: '10023126', meddra_version: '28.1' }],
};

describe('caseMissing', () => {
  it('names the four minimum criteria in the database order', () => {
    expect(caseMissing({})).toEqual(['patient', 'reporter', 'product', 'reaction']);
    expect(caseMissing(null)).toEqual(['patient', 'reporter', 'product', 'reaction']);
    expect(caseMissing(FULL)).toEqual([]);
  });

  it('needs a suspect product, and takes a paper reference as the reporter', () => {
    expect(caseMissing({ ...FULL, products: [{ name: 'Paracetamol', role: 'concomitant' }] })).toEqual(['product']);
    expect(caseMissing({ ...FULL, reporter: {}, literature_reference: 'Adel A. 2026.' })).toEqual([]);
  });

  it('does not count blanks', () => {
    expect(caseMissing({ ...FULL, patient: { initials: '  ' }, reactions: [{ verbatim: '' }] })).toEqual([
      'patient',
      'reaction',
    ]);
    expect(caseMissing({ ...FULL, patient: { age_value: 0 } })).toEqual([]);
  });
});

describe('the clock', () => {
  it('is 15 days until a reviewer says not serious, then 90', () => {
    expect(caseDue('2026-11-04', null)).toBe('2026-11-19');
    expect(caseDue('2026-11-04', true)).toBe('2026-11-19');
    expect(caseDue('2026-11-04', false)).toBe('2027-02-02');
  });

  it('counts calendar days across months and years', () => {
    expect(addDays('2026-12-25', 15)).toBe('2027-01-09');
    expect(addDays('2028-02-20', 10)).toBe('2028-03-01');
  });

  it('says how long is left or how late it is', () => {
    expect(clockLine('2026-11-19', '2026-11-06', true)).toBe('13 days left (due 2026-11-19)');
    expect(clockLine('2026-11-19', '2026-11-18', true)).toBe('1 day left (due 2026-11-19)');
    expect(clockLine('2026-11-19', '2026-11-19', true)).toBe('Due today (2026-11-19)');
    expect(clockLine('2026-11-19', '2026-11-21', true)).toBe('Overdue by 2 days (due 2026-11-19)');
    expect(clockLine('2026-11-19', '2026-11-21', false)).toBe('Was due 2026-11-19');
  });
});

describe('e2bProblems', () => {
  it('asks for the MedDRA code and version of each reaction, seriousness and confirmation', () => {
    expect(e2bProblems(FULL, true, 'confirmed')).toEqual([]);
    expect(e2bProblems({ ...FULL, reactions: [{ verbatim: 'jaundice' }] }, null, 'to_confirm')).toEqual([
      'seriousness is not decided',
      'the case is not confirmed',
      'reaction 1 needs its MedDRA LLT code (8 digits)',
      'reaction 1 needs its MedDRA version (e.g. 28.1)',
    ]);
  });

  it('asks each ingredient of a product for its name, a number and a unit the file knows', () => {
    const combo = {
      name: 'Carvexa 6.25 mg / 5 mg',
      role: 'suspect',
      ingredients: [
        { name: 'carvedilol', amount: 6.25, unit: 'mg' },
        { name: 'ivabradine', amount: 5, unit: 'mg' },
      ],
    };
    expect(e2bProblems({ ...FULL, products: [combo] }, true, 'confirmed')).toEqual([]);
    const bad = {
      ...combo,
      ingredients: [
        { name: '', amount: 6.25, unit: 'mg' },
        { name: 'ivabradine', amount: 5, unit: 'tablets' },
        { name: 'other', amount: -1, unit: 'mg' },
        { name: 'named only', amount: null, unit: null },
        { name: 'constructor', amount: 1, unit: 'constructor' },
      ],
    };
    expect(e2bProblems({ ...FULL, products: [bad] }, true, 'confirmed')).toEqual([
      'product 1 ingredient 1 needs its name',
      'product 1 ingredient 2 needs its unit (mg, g, µg, mL, IU or %)',
      'product 1 ingredient 3: the amount is not a number above zero',
      'product 1 ingredient 5 needs its unit (mg, g, µg, mL, IU or %)',
    ]);
  });
});

describe('field helpers', () => {
  it('stores a cleared field as not stated', () => {
    expect(orNull('  ')).toBeNull();
    expect(orNull(' A.M. ')).toBe('A.M.');
    expect(numberOrNull('61,5')).toBe(61.5);
    expect(numberOrNull('')).toBeNull();
    expect(numberOrNull('abc')).toBeNull();
  });

  it('encodes a file as base64', () => {
    expect(toBase64(new TextEncoder().encode('%PDF-1.7'))).toBe(btoa('%PDF-1.7'));
    const big = new Uint8Array(70000).fill(65);
    expect(atob(toBase64(big)).length).toBe(70000);
  });
});

describe('codingNorm', () => {
  // The same cases as tests/test_coding.py and supabase/tests/medical_coding.sql.
  it('compares words as the coder and the database do', () => {
    expect(codingNorm('  Hepatitis, Drug-Induced!! ')).toBe('hepatitis drug induced');
    expect(codingNorm('Ä Ödem')).toBe('Ä Ödem');
    expect(codingNorm('طفح جلدي، شديد')).toBe('طفح جلدي، شديد');
    expect(codingNorm(null)).toBe('');
  });

  it('finds the suggestions made for the same words, and none once the words changed', () => {
    const list = [{ text: 'Skin eruption', norm: 'skin eruption', suggestions: ['D005076'] }];
    expect(suggestionsFor(list, 'skin  eruption!', null)).toEqual(['D005076']);
    expect(suggestionsFor(list, 'itching')).toBeNull();
    expect(suggestionsFor(undefined, 'skin eruption')).toBeNull();
  });
});
