import { describe, expect, it } from 'vitest';
import {
  draftOf,
  draftProblems,
  emptyDraft,
  formatAmount,
  parsePick,
  pickOptions,
  pickValue,
  strengthLabel,
  suspectLine,
  toPayload,
  toProduct,
  withSuspect,
  type ProductItem,
  type ProductRaw,
} from './productForm';

const CARV = { id: 'c', inn_en: 'carvedilol' };
const IVAB = { id: 'i', inn_en: 'ivabradine' };

const RAW: ProductRaw = {
  id: 'p1',
  name: 'Carvexa',
  mah: 'Sato Pharma',
  dosage_form: 'film-coated tablet',
  active: true,
  product_ingredient: [{ ingredient: IVAB }, { ingredient: CARV }],
  product_strength: [
    {
      id: 's2',
      label: '12.5 mg / 7.5 mg',
      sort: 2,
      product_strength_part: [
        { ingredient_id: 'i', amount: '7.5', unit: 'mg' },
        { ingredient_id: 'c', amount: '12.5', unit: 'mg' },
      ],
    },
    {
      id: 's1',
      label: '6.25 mg / 5 mg',
      sort: 1,
      product_strength_part: [
        { ingredient_id: 'c', amount: 6.25, unit: 'mg' },
        { ingredient_id: 'i', amount: '5.000', unit: 'mg' },
      ],
    },
  ],
};

const CARVEXA: ProductItem = toProduct(RAW);

describe('toProduct', () => {
  it('orders the ingredients by name, the strengths by their order, and reads amounts as numbers', () => {
    expect(CARVEXA.ingredients.map((i) => i.inn_en)).toEqual(['carvedilol', 'ivabradine']);
    expect(CARVEXA.strengths.map((s) => s.id)).toEqual(['s1', 's2']);
    expect(CARVEXA.strengths[1].parts).toEqual([
      { ingredient_id: 'c', amount: 12.5, unit: 'mg' },
      { ingredient_id: 'i', amount: 7.5, unit: 'mg' },
    ]);
  });
});

describe('strength labels', () => {
  it('writes amounts as people do, in the order of the ingredients, as the database names them', () => {
    expect(formatAmount(5)).toBe('5');
    expect(formatAmount(6.25)).toBe('6.25');
    expect(formatAmount(0.1 + 0.2)).toBe('0.3');
    expect(strengthLabel(CARVEXA.strengths[0].parts.slice().reverse(), CARVEXA.ingredients)).toBe('6.25 mg / 5 mg');
  });
});

describe('the product draft', () => {
  it('says what is missing before it can be saved', () => {
    expect(draftProblems(emptyDraft())).toEqual(['Give the product’s name.', 'Choose the product’s ingredients.']);
    const d = { ...emptyDraft(), name: 'Carvexa', ingredients: ['c', 'i'] };
    d.strengths[0].amounts = { c: { amount: '6.25', unit: 'mg' }, i: { amount: '', unit: 'mg' } };
    expect(draftProblems(d)).toEqual(['Strength 1 needs an amount above zero for each ingredient.']);
    d.strengths[0].amounts.i = { amount: '5', unit: 'mg' };
    expect(draftProblems(d)).toEqual([]);
    d.strengths[0].amounts.i = { amount: '0', unit: 'mg' };
    expect(draftProblems(d)).toHaveLength(1);
  });

  it('goes to save_product with one amount per ingredient and keeps the ids of what exists', () => {
    const d = draftOf(CARVEXA);
    expect(d.strengths.map((s) => s.label)).toEqual(['', '']);   // built from the amounts, so built again
    d.strengths[0].amounts.c = { amount: '6,25', unit: 'mg' };
    const p = toPayload(d) as { id: string; ingredients: string[]; strengths: { id?: string; label: string | null; parts: unknown[] }[] };
    expect(p.id).toBe('p1');
    expect(p.ingredients).toEqual(['c', 'i']);
    expect(p.strengths[0]).toEqual({
      id: 's1',
      label: null,
      parts: [
        { ingredient_id: 'c', amount: 6.25, unit: 'mg' },
        { ingredient_id: 'i', amount: 5, unit: 'mg' },
      ],
    });
  });

  it('keeps a label typed by hand', () => {
    const d = draftOf({ ...CARVEXA, strengths: [{ ...CARVEXA.strengths[0], label: 'Carvexa 6.25' }] });
    expect(d.strengths[0].label).toBe('Carvexa 6.25');
  });
});

describe('a case picks a product or an ingredient', () => {
  it('reads and writes the one choice', () => {
    expect(parsePick(pickValue({ product: 'p1', ingredient: null }))).toEqual({ product: 'p1', ingredient: null });
    expect(parsePick(pickValue({ product: null, ingredient: 'c' }))).toEqual({ product: null, ingredient: 'c' });
    expect(pickValue({ product: null, ingredient: null })).toBe('');
    expect(parsePick('')).toEqual({ product: null, ingredient: null });
  });

  it('offers the products first, an archived one only to the case that names it, then the ingredients', () => {
    const old = { ...CARVEXA, id: 'p0', name: 'Old', active: false };
    const o = pickOptions([CARVEXA, old], [CARV, IVAB]);
    expect(o.products).toEqual([{ value: 'p:p1', label: 'Carvexa (carvedilol + ivabradine)' }]);
    expect(o.ingredients.map((x) => x.value)).toEqual(['i:c', 'i:i']);
    expect(pickOptions([CARVEXA, old], [], 'p0').products.map((x) => x.label)).toContain('Old (carvedilol + ivabradine) — archived');
  });

  it('fills the suspect line with the product, its strength and each ingredient with its amount', () => {
    const line = suspectLine(CARVEXA, CARVEXA.strengths[0]);
    expect(line).toEqual({
      name: 'Carvexa 6.25 mg / 5 mg',
      active_ingredient: 'carvedilol, ivabradine',
      role: 'suspect',
      ingredients: [
        { name: 'carvedilol', amount: 6.25, unit: 'mg' },
        { name: 'ivabradine', amount: 5, unit: 'mg' },
      ],
    });
    expect(suspectLine(CARVEXA, null).ingredients?.[0]).toEqual({ name: 'carvedilol', amount: null, unit: null });
  });

  it('keeps what the reviewer wrote on the suspect line, and adds one when there is none', () => {
    const line = suspectLine(CARVEXA, CARVEXA.strengths[0]);
    const form = {
      products: [
        { name: 'Paracetamol', role: 'concomitant' },
        { name: 'Carvexa', role: 'suspect', dose: 'one tablet twice daily', batch: 'B7' },
      ],
    };
    const filled = withSuspect(form, line);
    expect(filled.products?.[0]).toEqual(form.products[0]);
    expect(filled.products?.[1]).toMatchObject({ name: 'Carvexa 6.25 mg / 5 mg', dose: 'one tablet twice daily', batch: 'B7' });
    expect(filled.products?.[1].ingredients).toHaveLength(2);
    expect(withSuspect({ products: [{ name: 'Paracetamol', role: 'concomitant' }] }, line).products?.map((p) => p.name)).toEqual([
      'Carvexa 6.25 mg / 5 mg',
      'Paracetamol',
    ]);
  });
});
