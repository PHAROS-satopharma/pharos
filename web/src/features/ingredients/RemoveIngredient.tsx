// Removing an ingredient (administrators, 0100 remove_ingredient): one with nothing recorded against it is deleted;
// one with a record (a linked notice, a message, a signal, a case, a report, its label watch, our leaflet, a
// product) is paused instead and kept, and the answer says why.
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import '../../styles/drug-classes.css';
import { removedIngredientText, type RemoveIngredientResult } from './removeIngredient';

export function RemoveIngredient({ id, name }: { id: string; name: string }) {
  const qc = useQueryClient();
  const [asking, setAsking] = useState(false);
  const remove = useMutation({
    mutationFn: async () =>
      unwrap<RemoveIngredientResult>(await supabase.rpc('remove_ingredient', { p_id: id })),
    onSuccess: async () => {
      setAsking(false);
      await qc.invalidateQueries({ queryKey: ['ingredients'] });
    },
  });

  return (
    <div className="ing-remove" role="group" aria-label={`Remove ${name}`}>
      {remove.data ? <Notice tone="ok">{removedIngredientText(remove.data)}</Notice> : null}
      {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}
      {asking ? (
        <>
          <p className="small">
            Remove <strong>{name}</strong>? With nothing recorded against it, it is deleted with its names. With
            notices, messages, a signal, a case, a report, a label watch or a product, it is paused instead and
            everything is kept.
          </p>
          <div className="ing-remove-actions">
            <Button size="sm" variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
              Remove {name}
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setAsking(false)}>
              Keep it
            </Button>
          </div>
        </>
      ) : remove.data ? null : (
        <Button size="sm" variant="quiet" onClick={() => setAsking(true)}>
          Remove this ingredient
        </Button>
      )}
    </div>
  );
}
