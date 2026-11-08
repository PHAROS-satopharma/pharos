import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import '../../styles/cases.css';
import '../../styles/products.css';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import { useIngredients } from '../cases/CasesPage';
import {
  UNITS,
  draftOf,
  draftProblems,
  emptyDraft,
  emptyStrength,
  strengthLabel,
  toPayload,
  type ProductDraft,
  type ProductItem,
  type WatchedIngredient,
} from './productForm';
import { PRODUCTS_KEY, useProducts } from './useProducts';

const UNIT_OPTIONS = UNITS.map((u) => ({ value: u, label: u }));

/** Add or change one product: its name, MAH, dosage form, ingredients, and each strength's amounts. */
function ProductEditor({
  initial,
  watched,
  onDone,
}: {
  initial: ProductDraft;
  watched: WatchedIngredient[];
  onDone: (message: string) => void;
}) {
  const qc = useQueryClient();
  const [d, setD] = useState<ProductDraft>(initial);
  const problems = draftProblems(d);
  const chosen = watched.filter((i) => d.ingredients.includes(i.id));

  const save = useMutation({
    mutationFn: async (payload: Record<string, unknown>) =>
      unwrap<{ id: string; outcome: 'saved' | 'archived' | 'deleted' }>(await supabase.rpc('save_product', { p: payload })),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: PRODUCTS_KEY });
      onDone(
        r.outcome === 'archived'
          ? `${d.name} is archived: a case names it, so it stays on that case but is no longer offered.`
          : r.outcome === 'deleted'
            ? `${d.name} is taken off the list.`
            : `${d.name} is saved.`,
      );
    },
  });

  const setAmount = (k: number, ingredient: string, field: 'amount' | 'unit', v: string) =>
    setD({
      ...d,
      strengths: d.strengths.map((s, j) =>
        j === k
          ? { ...s, amounts: { ...s.amounts, [ingredient]: { ...(s.amounts[ingredient] ?? { amount: '', unit: 'mg' }), [field]: v } } }
          : s,
      ),
    });

  return (
    <form
      className="product-editor"
      onSubmit={(e) => {
        e.preventDefault();
        if (problems.length === 0) save.mutate(toPayload(d));
      }}
    >
      <div className="form-grid">
        <Field label="Product name" hint="As it is registered, e.g. Carvexa">
          <Input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} required maxLength={200} />
        </Field>
        <Field label="Marketing authorisation holder">
          <Input value={d.mah} onChange={(e) => setD({ ...d, mah: e.target.value })} />
        </Field>
        <Field label="Dosage form" hint="e.g. film-coated tablet">
          <Input value={d.dosage_form} onChange={(e) => setD({ ...d, dosage_form: e.target.value })} />
        </Field>
      </div>

      <fieldset className="product-group">
        <legend className="field-label">Ingredients</legend>
        <div className="product-ingredients">
          {watched.map((i) => (
            <Toggle
              key={i.id}
              label={i.inn_en}
              checked={d.ingredients.includes(i.id)}
              onChange={(on) =>
                setD({ ...d, ingredients: on ? [...d.ingredients, i.id] : d.ingredients.filter((x) => x !== i.id) })
              }
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="product-group">
        <legend className="field-label">Strengths</legend>
        {chosen.length === 0 ? <p className="muted small">Choose the ingredients first.</p> : null}
        {chosen.length > 0
          ? d.strengths.map((s, k) => (
              <div key={s.key} className="product-strength">
                <span className="micro">Strength {k + 1}</span>
                <div className="product-strength-row">
                  {chosen.map((i) => (
                    <div key={i.id} className="product-amount">
                      <Field label={`${i.inn_en}`}>
                        <Input
                          inputMode="decimal"
                          value={s.amounts[i.id]?.amount ?? ''}
                          onChange={(e) => setAmount(k, i.id, 'amount', e.target.value)}
                          aria-label={`Amount of ${i.inn_en}`}
                        />
                      </Field>
                      <Field label="Unit">
                        <Select
                          value={s.amounts[i.id]?.unit ?? 'mg'}
                          onChange={(e) => setAmount(k, i.id, 'unit', e.target.value)}
                          options={UNIT_OPTIONS}
                          aria-label={`Unit of ${i.inn_en}`}
                        />
                      </Field>
                    </div>
                  ))}
                  <Field label="Name of the strength" hint="Leave empty: it is named from the amounts">
                    <Input
                      value={s.label}
                      onChange={(e) => setD({ ...d, strengths: d.strengths.map((x, j) => (j === k ? { ...x, label: e.target.value } : x)) })}
                    />
                  </Field>
                </div>
                {d.strengths.length > 1 ? (
                  <Button
                    size="sm"
                    variant="quiet"
                    onClick={() => setD({ ...d, strengths: d.strengths.filter((_, j) => j !== k) })}
                  >
                    Remove this strength
                  </Button>
                ) : null}
              </div>
            ))
          : null}
        {chosen.length > 0 ? (
          <Button size="sm" onClick={() => setD({ ...d, strengths: [...d.strengths, emptyStrength()] })}>
            Add a strength
          </Button>
        ) : null}
      </fieldset>

      {d.id ? (
        <Toggle label="On the list (offered on new cases)" checked={d.active} onChange={(on) => setD({ ...d, active: on })} />
      ) : null}

      {problems.length > 0 && d.name.trim() ? (
        <ul className="product-problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
      <div className="case-actions">
        <Button type="submit" variant="primary" busy={save.isPending} disabled={problems.length > 0}>
          {d.id ? 'Save the product' : 'Add the product'}
        </Button>
        {d.id ? (
          <Button
            variant="danger"
            busy={save.isPending}
            title="A product a case names is archived, never deleted"
            onClick={() => save.mutate({ id: d.id, remove: true })}
          >
            Take off the list
          </Button>
        ) : null}
        <Button variant="quiet" onClick={() => onDone('')}>
          Cancel
        </Button>
      </div>
      {save.isError ? <Notice tone="error">{errorMessage(save.error)}</Notice> : null}
    </form>
  );
}

function Strengths({ p }: { p: ProductItem }) {
  if (p.strengths.length === 0) return <span className="muted">—</span>;
  return (
    <ul className="product-strengths">
      {p.strengths.map((s) => (
        <li key={s.id}>
          {s.label}
          {s.label !== strengthLabel(s.parts, p.ingredients) ? (
            <span className="muted small"> · {strengthLabel(s.parts, p.ingredients)}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/**
 * The Products tab (0099): the products of ours, each with its ingredients and strengths. A case is opened against
 * a product and its strength; the literature, the label watch and the reports stay per ingredient.
 */
export function ProductsPage() {
  const { isAdmin } = useAuth();
  const products = useProducts();
  const ingredients = useIngredients();
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [message, setMessage] = useState('');
  const watched = ingredients.data ?? [];
  const list = products.data ?? [];

  const done = (m: string) => {
    setEditing(null);
    setMessage(m);
  };

  return (
    <div className="page products-page">
      <PageHead
        eyebrow="Watchlist"
        title="Products"
        lede="Our products, each with its active ingredients and strengths. A case is opened against the product and its strength; the literature, the label watch and the reports follow each ingredient."
        actions={
          isAdmin && editing === null ? (
            <Button variant="primary" onClick={() => setEditing('new')}>
              Add a product
            </Button>
          ) : null
        }
      />
      {message ? <Notice tone="ok">{message}</Notice> : null}
      {isAdmin && editing === 'new' ? (
        <section className="panel">
          <SectionHead index="01" title="Add a product" />
          <ProductEditor initial={emptyDraft()} watched={watched} onDone={done} />
        </section>
      ) : null}
      <section className="panel">
        <SectionHead index={isAdmin && editing === 'new' ? '02' : '01'} title="Products" aside={`${list.filter((p) => p.active).length} on the list`} />
        {products.isPending ? (
          <Loading />
        ) : products.isError ? (
          <ErrorNote error={products.error} onRetry={() => products.refetch()} />
        ) : list.length === 0 ? (
          <Empty title="No product yet.">
            {isAdmin
              ? 'Add each product of ours with its ingredients and strengths, so a case can be opened against it.'
              : 'An administrator adds the products of ours with their ingredients and strengths.'}
          </Empty>
        ) : (
          <Table className="product-table">
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Ingredients</th>
                <th scope="col">Strengths</th>
                {isAdmin ? <th scope="col" aria-label="Change" /> : null}
              </tr>
            </thead>
            <tbody>
              {list.map((p) =>
                editing === p.id ? (
                  <tr key={p.id}>
                    <td colSpan={4}>
                      <ProductEditor
                        initial={draftOf(p)}
                        watched={[...watched, ...p.ingredients.filter((i) => !watched.some((w) => w.id === i.id))]}
                        onDone={done}
                      />
                    </td>
                  </tr>
                ) : (
                  <tr key={p.id} className={p.active ? undefined : 'is-archived'}>
                    <td>
                      <strong>{p.name}</strong> {p.active ? null : <Tag tone="quiet">Archived</Tag>}
                      <span className="case-sub">{[p.dosage_form, p.mah].filter(Boolean).join(' · ') || '—'}</span>
                    </td>
                    <td>{p.ingredients.map((i) => i.inn_en).join(' + ') || '—'}</td>
                    <td>
                      <Strengths p={p} />
                    </td>
                    {isAdmin ? (
                      <td>
                        {editing === null ? (
                          <Button size="sm" onClick={() => setEditing(p.id)}>
                            Change
                          </Button>
                        ) : null}
                      </td>
                    ) : null}
                  </tr>
                ),
              )}
            </tbody>
          </Table>
        )}
      </section>
    </div>
  );
}
