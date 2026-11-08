/**
 * The product list (migration 0099): a product of ours with its ingredients and strengths, the draft the Products
 * tab edits, and how a case picks a product or a single ingredient and fills its suspect drug line.
 *
 * The strength label is built the way the database builds it (product_strength_label()): each ingredient's
 * amount and unit, in the order of the ingredients' names, joined by " / " — "6.25 mg / 5 mg".
 */
import type { CaseForm, Product as CaseProduct, ProductIngredient } from '../cases/caseForm';

/** The units save_product() takes (product_strength_part.unit). */
export const UNITS = ['mg', 'g', 'µg', 'mL', 'IU', '%'] as const;
export type Unit = (typeof UNITS)[number];

export interface WatchedIngredient {
  id: string;
  inn_en: string;
}

export interface StrengthPart {
  ingredient_id: string;
  amount: number;
  unit: string;
}

export interface Strength {
  id: string;
  label: string;
  sort: number;
  parts: StrengthPart[];
}

export interface ProductItem {
  id: string;
  name: string;
  mah: string | null;
  dosage_form: string | null;
  active: boolean;
  ingredients: WatchedIngredient[];
  strengths: Strength[];
}

/** The select of the product list, nested as PostgREST answers it. */
export const PRODUCT_SELECT =
  'id, name, mah, dosage_form, active, product_ingredient(ingredient:ingredient_id(id, inn_en)), ' +
  'product_strength(id, label, sort, product_strength_part(ingredient_id, amount, unit))';

export interface ProductRaw {
  id: string;
  name: string;
  mah: string | null;
  dosage_form: string | null;
  active: boolean;
  product_ingredient: { ingredient: WatchedIngredient | null }[] | null;
  product_strength:
    | { id: string; label: string; sort: number; product_strength_part: { ingredient_id: string; amount: number | string; unit: string }[] | null }[]
    | null;
}

/** One product as the screens use it: ingredients by name, strengths in their order, parts in ingredient order. */
export function toProduct(raw: ProductRaw): ProductItem {
  const ingredients = (raw.product_ingredient ?? [])
    .map((x) => x.ingredient)
    .filter((x): x is WatchedIngredient => Boolean(x))
    .sort((a, b) => a.inn_en.localeCompare(b.inn_en));
  const order = new Map(ingredients.map((i, k) => [i.id, k]));
  const strengths = (raw.product_strength ?? [])
    .map((s) => ({
      id: s.id,
      label: s.label,
      sort: s.sort,
      parts: (s.product_strength_part ?? [])
        .map((p) => ({ ingredient_id: p.ingredient_id, amount: Number(p.amount), unit: p.unit }))
        .sort((a, b) => (order.get(a.ingredient_id) ?? 0) - (order.get(b.ingredient_id) ?? 0)),
    }))
    .sort((a, b) => a.sort - b.sort || a.label.localeCompare(b.label));
  return { id: raw.id, name: raw.name, mah: raw.mah, dosage_form: raw.dosage_form, active: raw.active, ingredients, strengths };
}

/** An amount as people write it: 6.25, 5, 0.5 (never 5.000). */
export function formatAmount(n: number): string {
  return String(Number(n.toFixed(6)));
}

/** "6.25 mg / 5 mg": the amounts in the order of the ingredients' names, as the database names a strength. */
export function strengthLabel(parts: StrengthPart[], ingredients: WatchedIngredient[]): string {
  const name = new Map(ingredients.map((i) => [i.id, i.inn_en]));
  return [...parts]
    .sort((a, b) => (name.get(a.ingredient_id) ?? '').localeCompare(name.get(b.ingredient_id) ?? ''))
    .map((p) => `${formatAmount(p.amount)} ${p.unit}`)
    .join(' / ');
}

// ───────────────────────────── the draft the Products tab edits ─────────────────────────────

export interface StrengthDraft {
  key: string;
  id?: string;
  label: string;
  amounts: Record<string, { amount: string; unit: string }>;
}

export interface ProductDraft {
  id?: string;
  name: string;
  mah: string;
  dosage_form: string;
  active: boolean;
  ingredients: string[];
  strengths: StrengthDraft[];
}

let keys = 0;
export function newKey(): string {
  keys += 1;
  return `s${keys}`;
}

export function emptyStrength(): StrengthDraft {
  return { key: newKey(), label: '', amounts: {} };
}

export function emptyDraft(): ProductDraft {
  return { name: '', mah: 'Sato Pharma', dosage_form: '', active: true, ingredients: [], strengths: [emptyStrength()] };
}

export function draftOf(p: ProductItem): ProductDraft {
  return {
    id: p.id,
    name: p.name,
    mah: p.mah ?? '',
    dosage_form: p.dosage_form ?? '',
    active: p.active,
    ingredients: p.ingredients.map((i) => i.id),
    strengths: p.strengths.map((s) => ({
      key: newKey(),
      id: s.id,
      // A label the database built from the amounts is built again when they change; one typed by hand stays.
      label: s.label === strengthLabel(s.parts, p.ingredients) ? '' : s.label,
      amounts: Object.fromEntries(s.parts.map((x) => [x.ingredient_id, { amount: formatAmount(x.amount), unit: x.unit }])),
    })),
  };
}

function amountOf(text: string | undefined): number | null {
  const t = (text ?? '').trim().replace(',', '.');
  if (t === '' || !/^\d*\.?\d+$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** What stops the draft from being saved, in plain words (empty when it can be saved). */
export function draftProblems(d: ProductDraft): string[] {
  const out: string[] = [];
  if (!d.name.trim()) out.push('Give the product’s name.');
  if (d.ingredients.length === 0) out.push('Choose the product’s ingredients.');
  if (d.strengths.length === 0) out.push('Give at least one strength.');
  d.strengths.forEach((s, k) => {
    if (d.ingredients.some((i) => amountOf(s.amounts[i]?.amount) === null)) {
      out.push(`Strength ${k + 1} needs an amount above zero for each ingredient.`);
    }
  });
  return out;
}

/** The draft as save_product() takes it. */
export function toPayload(d: ProductDraft): Record<string, unknown> {
  return {
    ...(d.id ? { id: d.id } : {}),
    name: d.name.trim(),
    mah: d.mah.trim() || null,
    dosage_form: d.dosage_form.trim() || null,
    active: d.active,
    ingredients: d.ingredients,
    strengths: d.strengths.map((s) => ({
      ...(s.id ? { id: s.id } : {}),
      label: s.label.trim() || null,
      parts: d.ingredients.map((i) => ({
        ingredient_id: i,
        amount: amountOf(s.amounts[i]?.amount),
        unit: s.amounts[i]?.unit || 'mg',
      })),
    })),
  };
}

// ───────────────────────────── a case picks a product or an ingredient ─────────────────────────────

export interface Pick {
  product: string | null;
  ingredient: string | null;
}

/** The value of the "Product or ingredient" choice: p:<id> for a product, i:<id> for a single ingredient. */
export function pickValue(p: Pick): string {
  if (p.product) return `p:${p.product}`;
  if (p.ingredient) return `i:${p.ingredient}`;
  return '';
}

export function parsePick(value: string): Pick {
  if (value.startsWith('p:')) return { product: value.slice(2), ingredient: null };
  if (value.startsWith('i:')) return { product: null, ingredient: value.slice(2) };
  return { product: null, ingredient: null };
}

/** The products on the list first (and an archived one the case already names), then the single ingredients. */
export function pickOptions(
  products: ProductItem[],
  ingredients: WatchedIngredient[],
  current: string | null = null,
): { products: { value: string; label: string }[]; ingredients: { value: string; label: string }[] } {
  return {
    products: products
      .filter((p) => p.active || p.id === current)
      .map((p) => ({
        value: `p:${p.id}`,
        label: `${p.name} (${p.ingredients.map((i) => i.inn_en).join(' + ')})${p.active ? '' : ' — archived'}`,
      })),
    ingredients: ingredients.map((i) => ({ value: `i:${i.id}`, label: i.inn_en })),
  };
}

/** The suspect drug line of a product: its name and strength, and each ingredient with its amount. */
export function suspectLine(product: ProductItem, strength: Strength | null): CaseProduct {
  const amounts = new Map((strength?.parts ?? []).map((p) => [p.ingredient_id, p]));
  const ingredients: ProductIngredient[] = product.ingredients.map((i) => ({
    name: i.inn_en,
    amount: amounts.get(i.id)?.amount ?? null,
    unit: amounts.get(i.id)?.unit ?? null,
  }));
  return {
    name: strength ? `${product.name} ${strength.label}` : product.name,
    active_ingredient: product.ingredients.map((i) => i.inn_en).join(', '),
    role: 'suspect',
    ingredients,
  };
}

/**
 * The form with its first suspect line filled from the product (what the reviewer wrote about dose, dates or batch
 * stays); a form without a suspect line gets one first.
 */
export function withSuspect(form: CaseForm, line: CaseProduct): CaseForm {
  const products = form.products ?? [];
  const at = products.findIndex((p) => p.role === 'suspect');
  if (at < 0) return { ...form, products: [line, ...products] };
  return {
    ...form,
    products: products.map((p, k) =>
      k === at ? { ...p, name: line.name, active_ingredient: line.active_ingredient, ingredients: line.ingredients } : p,
    ),
  };
}
