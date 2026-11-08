import { describe, expect, it } from 'vitest';
import { e2bProblems, type CaseForm, type Reaction } from '../cases/caseForm';
import { conceptPath, ctcaeGrade, ctcaeGrades, needsMeddra, sourcesUsed, withTerm, type ReactionTerm } from './terms';

const NCIT: ReactionTerm = {
  source: 'ncit',
  code: 'C9000002',
  name: 'Test Insomnia',
  version: '2099-10-28',
  coded_by: 'CI Reviewer',
  coded_at: '2099-11-08T10:00:00Z',
};

describe('needsMeddra', () => {
  it('asks for an official LLT until the reaction has 8 digits, whatever free code it carries', () => {
    expect(needsMeddra({})).toBe(true);
    expect(needsMeddra({ meddra_llt_code: 'C9000002' })).toBe(true);
    expect(needsMeddra({ meddra_llt_code: ' 99999999 ' })).toBe(false);
  });
});

describe('a free code never reaches the E2B file', () => {
  it('leaves the MedDRA problems standing when a reaction has only a free code', () => {
    const form: CaseForm = {
      patient: { initials: 'A.M.' },
      reporter: { qualification: 'physician' },
      products: [{ name: 'Testamine 8 mg', role: 'suspect' }],
      reactions: [withTerm<Reaction>({ verbatim: 'cannot sleep' }, NCIT)],
    };
    expect(e2bProblems(form, true, 'confirmed')).toEqual([
      'reaction 1 needs its MedDRA LLT code (8 digits)',
      'reaction 1 needs its MedDRA version (e.g. 28.1)',
    ]);
  });
});

describe('withTerm', () => {
  it('keeps the MedDRA fields and the MeSH code as they were for a non-MeSH code', () => {
    const r = withTerm<Reaction>({ verbatim: 'x', mesh_ui: 'D000001', mesh_term: 'Old', meddra_llt_code: null }, NCIT);
    expect(r).toEqual({ verbatim: 'x', mesh_ui: 'D000001', mesh_term: 'Old', meddra_llt_code: null, term: NCIT });
  });
  it('also fills the MeSH code when the choice is MeSH, and removes only the free code', () => {
    const mesh: ReactionTerm = { ...NCIT, source: 'mesh', code: 'D000002', name: 'Test Insomnia' };
    const r = withTerm<Reaction>({ verbatim: 'x' }, mesh);
    expect([r.mesh_ui, r.mesh_term]).toEqual(['D000002', 'Test Insomnia']);
    expect(withTerm(r, null)).toEqual({ ...r, term: null });
  });
});

describe('CTCAE grades', () => {
  it('reads the grade of a CTCAE child, and nothing else', () => {
    expect(ctcaeGrade('Grade 2 Test Nausea, CTCAE 6.0')).toBe(2);
    expect(ctcaeGrade('Grade 2 Test Nausea')).toBeNull();
    expect(ctcaeGrade('Test Nausea, CTCAE 6.0')).toBeNull();
    const grades = ctcaeGrades([
      { name: 'Grade 3 Test Nausea, CTCAE 6.0' },
      { name: 'Test Morning Nausea' },
      { name: 'Grade 1 Test Nausea, CTCAE 6.0' },
    ]);
    expect(grades.map((g) => g.grade)).toEqual([1, 3]);
  });
});

describe('sourcesUsed and conceptPath', () => {
  it('names each source once, in the page order', () => {
    expect(sourcesUsed([{ term: { ...NCIT, source: 'mesh' } }, { term: NCIT }, {}, { term: NCIT }])).toEqual(['ncit', 'mesh']);
    expect(sourcesUsed(null)).toEqual([]);
  });
  it('escapes a code in the address', () => {
    expect(conceptPath('icd11', 'BlockL1-1A0')).toBe('/terminology/icd11/BlockL1-1A0');
    expect(conceptPath('oae', 'a/b')).toBe('/terminology/oae/a%2Fb');
  });
});
