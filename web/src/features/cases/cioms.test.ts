import { describe, expect, it } from 'vitest';
import { e2bProblems, type CaseForm } from './caseForm';
import { ciomsDate, ciomsHtml, ciomsProblems, esc, productLine, reactionLine, therapyDays } from './cioms';

// A confirmed case with no MedDRA code: the E2B file is blocked, the CIOMS I form is not.
const CASE: CaseForm = {
  report_type: 'spontaneous',
  country: 'EG',
  patient: { initials: 'A.M.', sex: 'female', age_value: 54, age_unit: 'year', medical_history: 'Type 2 diabetes' },
  reporter: { name: 'Dr Hany', qualification: 'physician', organisation: 'Zagazig University Hospital' },
  products: [
    {
      name: 'Royafloxacin 500 mg',
      role: 'suspect',
      ingredients: [{ name: 'levofloxacin', amount: 500, unit: 'mg' }],
      dose: '500 mg once daily',
      route: 'oral',
      indication: 'sinusitis',
      start_date: '2026-10-01',
      stop_date: '2026-10-05',
      action_taken: 'withdrawn',
    },
    { name: 'Metformin 850 mg', role: 'concomitant', start_date: '2025-01' },
  ],
  reactions: [
    {
      verbatim: 'ألم في وتر العرقوب',
      english: 'Achilles tendon pain',
      onset_date: '2026-10-04',
      outcome: 'recovering',
      criteria: ['disability'],
    },
  ],
  narrative: 'Pain began on day 4 of therapy <and> settled after stopping.',
};

const INPUT = { form: CASE, ref: 'C-2026-0007', dayZero: '2026-10-06', serious: true, followUp: false, today: '2026-11-08' };

describe('ciomsProblems', () => {
  it('needs no MedDRA code, unlike the E2B file', () => {
    expect(e2bProblems(CASE, true, 'confirmed')).toContain('reaction 1 needs its MedDRA LLT code (8 digits)');
    expect(ciomsProblems(CASE, true, 'confirmed')).toEqual([]);
  });

  it('still needs the four minimum criteria, a seriousness decision and a confirmed case', () => {
    expect(ciomsProblems({}, null, 'to_confirm')).toEqual([
      'the case has no patient yet',
      'the case has no reporter yet',
      'the case has no product yet',
      'the case has no reaction yet',
      'seriousness is not decided',
      'the case is not confirmed',
    ]);
    expect(ciomsProblems(CASE, false, 'sent')).toEqual([]);
  });
});

describe('the boxes', () => {
  it('writes dates the CIOMS way', () => {
    expect(ciomsDate('2026-05-03')).toBe('03 MAY 2026');
    expect(ciomsDate('2026-05')).toBe('MAY 2026');
    expect(ciomsDate('2026')).toBe('2026');
    expect(ciomsDate('2026-13')).toBe('2026-13');
    expect(ciomsDate(null)).toBe('');
  });

  it('counts therapy days only between two full dates', () => {
    expect(therapyDays('2026-10-01', '2026-10-05')).toBe(5);
    expect(therapyDays('2026-10', '2026-10-05')).toBeNull();
    expect(therapyDays('2026-10-05', '2026-10-01')).toBeNull();
  });

  it('names the product with its generic name and strength', () => {
    expect(productLine(CASE.products![0])).toBe('Royafloxacin 500 mg (levofloxacin 500 mg)');
    expect(productLine({ name: 'Paracetamol', active_ingredient: 'paracetamol' })).toBe('Paracetamol');
  });

  it('gives the reaction in English with the words as reported, and a MedDRA code only when typed', () => {
    const line = reactionLine(CASE.reactions![0], 0);
    expect(line).toContain('1. Achilles tendon pain (reported as: “⁨ألم في وتر العرقوب⁩”)');
    expect(line).toContain('onset 04 OCT 2026');
    expect(line).toContain('serious: disability');
    expect(line).not.toContain('MedDRA');
    expect(reactionLine({ verbatim: 'jaundice', meddra_llt_code: '10023126', meddra_version: '29.1' }, 1)).toBe(
      '2. jaundice — MedDRA LLT 10023126 (v29.1)',
    );
  });
});

describe('ciomsHtml', () => {
  const html = ciomsHtml(INPUT);

  it('fills the four sections from the case', () => {
    expect(html).toContain('CIOMS FORM');
    expect(html).toContain('A.M.');
    expect(html).toContain('54 years');
    expect(html).toContain('04 OCT 2026');
    expect(html).toContain('Royafloxacin 500 mg (levofloxacin 500 mg)');
    expect(html).toContain('5 days');
    expect(html).toContain('Metformin 850 mg, JAN 2025');
    expect(html).toContain('Type 2 diabetes');
    expect(html).toContain('C-2026-0007');
    expect(html).toContain('06 OCT 2026');
    expect(html).toContain('Sato Pharma, Egypt');
  });

  it('ticks the criteria, the source and the report type that apply, and no others', () => {
    expect(html).toContain('<span class="box">✕</span>Involved persistent or significant disability or incapacity');
    expect(html).toContain('<span class="box"></span>Patient died');
    expect(html).toContain('<span class="box">✕</span>Health professional');
    expect(html).toContain('<span class="box"></span>Literature');
    expect(html).toContain('<span class="box">✕</span>Initial');
    expect(ciomsHtml({ ...INPUT, followUp: true })).toContain('<span class="box">✕</span>Follow-up');
  });

  it('escapes the case text', () => {
    expect(html).toContain('therapy &lt;and&gt; settled');
    expect(html).not.toContain('<and>');
    expect(esc(`<script>"x"&'y'`)).toBe('&lt;script&gt;&quot;x&quot;&amp;&#39;y&#39;');
  });

  it('never prints a MeSH code', () => {
    const coded = ciomsHtml({
      ...INPUT,
      form: { ...CASE, reactions: [{ ...CASE.reactions![0], mesh_ui: 'D000070639', mesh_term: 'Tendinopathy' }] },
    });
    expect(coded).not.toContain('D000070639');
    expect(coded).not.toContain('Tendinopathy');
  });
});
