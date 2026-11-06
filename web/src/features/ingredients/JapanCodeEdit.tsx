// The Japan code of an ingredient that is already on the watchlist, on its open row of the Ingredients page, for
// administrators: set_japan_code() (migration 0052) stores the 7-character code and replaces the previous one.
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import type { IngredientTerm } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import { JapanCodeField } from './JapanCodeField';
import { currentJapanCode, japanCodeOf } from './japanCode';

export function JapanCodeEdit({ ingredientId, terms }: { ingredientId: string; terms: IngredientTerm[] }) {
  const qc = useQueryClient();
  const current = currentJapanCode(terms);
  const [draft, setDraft] = useState(current ?? '');
  const code = japanCodeOf(draft);

  const save = useMutation({
    mutationFn: async (next: string) =>
      unwrap<string>(await supabase.rpc('set_japan_code', { p_ingredient: ingredientId, p_code: next })),
    onSuccess: async (saved) => {
      setDraft(saved);
      // The row's terms and its readiness line ("No Japan code yet") read the new code.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['ingredients'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-readiness', ingredientId] }),
      ]);
    },
  });

  return (
    <section className="dc-section japan-code-edit" aria-label="Japan code">
      <JapanCodeField
        value={draft}
        current={current}
        onChange={(next) => {
          setDraft(next);
          if (!save.isPending) save.reset();
        }}
        action={
          <Button
            variant="primary"
            size="sm"
            busy={save.isPending}
            disabled={!code || code === current}
            onClick={() => {
              if (code) save.mutate(code);
            }}
          >
            Save
          </Button>
        }
      >
        {save.isSuccess ? (
          <Notice tone="ok">Japan code {save.data} saved. Japan’s label watch uses it at its next weekly run.</Notice>
        ) : null}
        {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      </JapanCodeField>
    </section>
  );
}
