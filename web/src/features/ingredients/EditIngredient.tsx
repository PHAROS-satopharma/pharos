// Editing an ingredient that is already on the watchlist, on its open row of the Ingredients page, for
// administrators: its English name and every name it is looked for under (change, add, remove). Adding goes
// through save_ingredient, which only ever adds; this writes the rows themselves (editTerms.ts says how).
import { useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { useCountryIndex } from '../../lib/regulators';
import type { IngredientTerm } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { TermEditor, type TermDraft } from './TermEditor';
import { draftsOf, isEmptyPlan, planTermEdit } from './editTerms';

export function EditIngredient({
  ingredient,
  onDone,
}: {
  ingredient: { id: string; inn_en: string; ingredient_term: IngredientTerm[] };
  onDone: (saved: boolean) => void;
}) {
  const { person } = useAuth();
  const qc = useQueryClient();
  const countries = useCountryIndex();
  const [inn, setInn] = useState(ingredient.inn_en);
  const [terms, setTerms] = useState<TermDraft[]>(() => draftsOf(ingredient.ingredient_term));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const countryOptions = useMemo(
    () =>
      countries.names
        .map((n) => ({ value: countries.codeOf(n) ?? '', label: n }))
        .filter((o) => o.value !== ''),
    [countries],
  );

  async function save() {
    if (!person) return;
    setSaveError(null);
    let plan;
    try {
      plan = planTermEdit(ingredient.ingredient_term, terms);
    } catch (e) {
      setSaveError(errorMessage(e));
      return;
    }
    const name = inn.trim();
    const renamed = name !== ingredient.inn_en;
    if (!renamed && isEmptyPlan(plan)) {
      onDone(false);
      return;
    }
    setSaving(true);
    const stamp = { verified_by: person.id, verified_at: new Date().toISOString() };
    try {
      if (renamed) {
        unwrapChanged(
          await supabase.from('ingredient').update({ inn_en: name }).eq('id', ingredient.id).select('id'),
          'this ingredient',
        );
      }
      // Removed first, so a word moved from one row to another never meets itself.
      if (plan.remove.length) {
        unwrapChanged(
          await supabase.from('ingredient_term').delete().in('id', plan.remove).select('id'),
          'these names',
        );
      }
      for (const u of plan.update) {
        unwrapChanged(
          await supabase
            .from('ingredient_term')
            .update({ ...u.row, ...stamp })
            .eq('id', u.id)
            .select('id'),
          `“${u.row.term}”`,
        );
      }
      if (plan.insert.length) {
        unwrap(
          await supabase
            .from('ingredient_term')
            .insert(plan.insert.map((r) => ({ ...r, ingredient_id: ingredient.id, ...stamp })))
            .select('id'),
        );
      }
      onDone(true);
    } catch (e) {
      setSaveError(`Not all saved: ${errorMessage(e)}. The list below shows what the database holds now.`);
    } finally {
      setSaving(false);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['ingredients'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-names'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-list'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-readiness', ingredient.id] }),
      ]);
    }
  }

  const count = terms.filter((t) => t.term.trim()).length;
  return (
    <section className="panel add-panel edit-panel" aria-labelledby={`edit-${ingredient.id}`}>
      <div className="panel-head">
        <h2 id={`edit-${ingredient.id}`} className="panel-title">
          Edit {ingredient.inn_en}
        </h2>
      </div>
      <Field label="Name in English">
        <Input value={inn} onChange={(e) => setInn(e.target.value)} aria-label="Name in English" />
      </Field>
      <p className="small muted">
        Change a name, add one, or remove one. A new or changed name is looked for from now on, and within hours the notices
        of the last 12 months are checked for it. The Japan code has its own field above.
      </p>
      <TermEditor
        terms={terms}
        onChange={setTerms}
        languages={countries.languages}
        countries={countryOptions}
        withJapanCode={false}
      />
      {saveError ? <Notice tone="error">{saveError}</Notice> : null}
      <div className="panel-foot">
        <Button variant="primary" busy={saving} disabled={count === 0 || !inn.trim()} onClick={() => void save()}>
          Save {count} {count === 1 ? 'name' : 'names'}
        </Button>
        <Button variant="quiet" disabled={saving} onClick={() => onDone(false)}>
          Cancel
        </Button>
      </div>
    </section>
  );
}
