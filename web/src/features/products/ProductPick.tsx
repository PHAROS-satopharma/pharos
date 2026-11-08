import { Field } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { parsePick, pickOptions, pickValue, type ProductItem, type Strength, type WatchedIngredient } from './productForm';
import { useProducts } from './useProducts';

export interface PickState {
  product: string | null;
  strength: string | null;
  ingredient: string | null;
}

/** What a pick means: the product and strength chosen (null for a single ingredient or nothing). */
export function pickedProduct(
  products: ProductItem[] | undefined,
  pick: PickState,
): { product: ProductItem | null; strength: Strength | null } {
  const product = (products ?? []).find((p) => p.id === pick.product) ?? null;
  const strength = product?.strengths.find((s) => s.id === pick.strength) ?? null;
  return { product, strength };
}

/**
 * "Product or ingredient": the products on the list first, then the single ingredients; when a product is picked,
 * its "Strength". A product with one strength takes it at once.
 */
export function ProductPick({
  value,
  ingredients,
  onChange,
  disabled,
  placeholder,
  current = null,
}: {
  value: PickState;
  ingredients: WatchedIngredient[];
  onChange: (next: PickState, product: ProductItem | null, strength: Strength | null) => void;
  disabled?: boolean;
  placeholder: string;
  /** The product the case names now, offered even when it was archived since. */
  current?: string | null;
}) {
  const products = useProducts();
  const options = pickOptions(products.data ?? [], ingredients, current);
  const { product } = pickedProduct(products.data, value);

  function choose(v: string) {
    const p = parsePick(v);
    const chosen = (products.data ?? []).find((x) => x.id === p.product) ?? null;
    const strength = chosen && chosen.strengths.length === 1 ? chosen.strengths[0] : null;
    onChange({ product: p.product, ingredient: p.ingredient, strength: strength?.id ?? null }, chosen, strength);
  }

  function chooseStrength(id: string) {
    const strength = product?.strengths.find((s) => s.id === id) ?? null;
    onChange({ ...value, strength: strength?.id ?? null }, product, strength);
  }

  return (
    <>
      <Field label="Product or ingredient" hint={products.isError ? 'The product list could not be loaded.' : undefined}>
        <Select
          value={pickValue({ product: value.product, ingredient: value.product ? null : value.ingredient })}
          onChange={(e) => choose(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
        >
          {options.products.length > 0 ? (
            <optgroup label="Products">
              {options.products.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </optgroup>
          ) : null}
          <optgroup label="Single ingredients">
            {options.ingredients.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        </Select>
      </Field>
      {product ? (
        <Field label="Strength">
          <Select
            value={value.strength ?? ''}
            onChange={(e) => chooseStrength(e.target.value)}
            placeholder="Not known yet"
            options={product.strengths.map((s) => ({ value: s.id, label: s.label }))}
            disabled={disabled}
          />
        </Field>
      ) : null}
    </>
  );
}
