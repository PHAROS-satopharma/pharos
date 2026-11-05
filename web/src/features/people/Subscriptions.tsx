import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { SUB_KIND_LABEL } from '../../lib/labels';
import type { SubKind, SubscriptionRow } from '../../lib/types';
import { useIngredientList } from './useIngredientList';
import { Button } from '../../ui/Button';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';

export function describeSub(s: SubscriptionRow): string {
  if (s.kind === 'ingredient') return `${s.ingredient?.inn_en ?? 'Every ingredient'}, immediately`;
  return SUB_KIND_LABEL[s.kind];
}

/** One person's Telegram subscriptions: a plain list, each removable, and one row to add. */
export function SubscriptionEditor({
  personId,
  subs,
  allowHealth,
  invalidate,
}: {
  personId: string;
  subs: SubscriptionRow[];
  allowHealth: boolean;
  /** Query keys to refresh after a change. */
  invalidate: string[][];
}) {
  const qc = useQueryClient();
  const ingredients = useIngredientList();
  const [kind, setKind] = useState<SubKind>('ingredient');
  const [ingredientId, setIngredientId] = useState('');

  const refresh = async () => {
    await Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: k })));
  };

  const add = useMutation({
    mutationFn: async () => {
      unwrap<null>(
        await supabase.from('subscription').insert({
          person_id: personId,
          kind,
          ingredient_id: kind === 'ingredient' && ingredientId ? ingredientId : null,
        }),
      );
    },
    onSuccess: async () => {
      setIngredientId('');
      await refresh();
    },
  });

  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrapChanged(await supabase.from('subscription').delete().eq('id', id).select('id'), 'this alert');
    },
    onSuccess: refresh,
  });

  const duplicate = subs.some(
    (s) => s.kind === kind && (kind !== 'ingredient' || (s.ingredient_id ?? '') === ingredientId),
  );
  const kinds: SubKind[] = allowHealth ? ['ingredient', 'class_digest', 'admin_health'] : ['ingredient', 'class_digest'];

  return (
    <div className="subs">
      {subs.length === 0 ? (
        <p className="muted small">No messages are sent to this person.</p>
      ) : (
        <ul className="subs-list">
          {subs.map((s) => (
            <li key={s.id}>
              <span>{describeSub(s)}</span>
              <Button size="sm" variant="quiet" busy={remove.isPending && remove.variables === s.id} onClick={() => remove.mutate(s.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="subs-add">
        <Select
          aria-label="What to receive"
          value={kind}
          onChange={(e) => setKind(e.target.value as SubKind)}
          options={kinds.map((k) => ({ value: k, label: SUB_KIND_LABEL[k] }))}
        />
        {kind === 'ingredient' ? (
          <Select
            aria-label="Which ingredient"
            value={ingredientId}
            onChange={(e) => setIngredientId(e.target.value)}
            placeholder="Every ingredient"
            options={(ingredients.data ?? []).map((i) => ({ value: i.id, label: i.inn_en }))}
          />
        ) : null}
        <Button size="sm" busy={add.isPending} disabled={duplicate} onClick={() => add.mutate()}>
          {duplicate ? 'Already on' : 'Add'}
        </Button>
      </div>
      {add.isError ? <Notice tone="error">Not added: {errorMessage(add.error)}</Notice> : null}
      {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}
    </div>
  );
}
