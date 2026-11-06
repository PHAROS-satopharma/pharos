// The Japan codes of an ingredient that is already on the watchlist, on its open row of the Ingredients page, for
// administrators: set_japan_codes() (migration 0069) stores the 7-character codes typed and removes the ones left out.
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import type { IngredientTerm } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import { JapanCodeField } from './JapanCodeField';
import { currentJapanCodes, japanCodesOf, sameJapanCodes } from './japanCode';

export function JapanCodeEdit({ ingredientId, terms }: { ingredientId: string; terms: IngredientTerm[] }) {
  const qc = useQueryClient();
  const current = currentJapanCodes(terms);
  const [draft, setDraft] = useState(current.join(', '));
  const { codes, wrong } = japanCodesOf(draft);

  const save = useMutation({
    mutationFn: async (next: string[]) =>
      unwrap<string[]>(await supabase.rpc('set_japan_codes', { p_ingredient: ingredientId, p_codes: next })),
    onSuccess: async (saved) => {
      setDraft(saved.join(', '));
      // The row's terms and its readiness line ("No Japan code yet") read the new codes.
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['ingredients'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-readiness', ingredientId] }),
      ]);
    },
  });

  return (
    <section className="dc-section japan-code-edit" aria-label="Japan codes">
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
            disabled={codes.length === 0 || wrong.length > 0 || sameJapanCodes(codes, current)}
            onClick={() => save.mutate(codes)}
          >
            Save
          </Button>
        }
      >
        {save.isSuccess ? (
          <Notice tone="ok">
            {save.data.length > 1 ? `Japan codes ${save.data.join(', ')} saved.` : `Japan code ${save.data[0]} saved.`}{' '}
            Japan’s label watch uses {save.data.length > 1 ? 'them' : 'it'} at its next weekly run.
          </Notice>
        ) : null}
        {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      </JapanCodeField>
    </section>
  );
}
