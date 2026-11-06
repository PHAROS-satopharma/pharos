import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Notice } from '../../ui/States';

/**
 * A pharmacotherapeutic group added by hand (add_search_group, migration 0049): named in words, never an ATC
 * code. An existing class with that name is reused; a new one starts with no words, which the administrator
 * adds on its line. The groups from the ATC code are the daily run's.
 */
export function AddGroup({ ingredientId, ingredientName }: { ingredientId: string; ingredientName: string }) {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const add = useMutation({
    mutationFn: async () => {
      unwrap(await supabase.rpc('add_search_group', { p_ingredient: ingredientId, p_name_en: name.trim() }));
    },
    onSuccess: async () => {
      setName('');
      await qc.invalidateQueries({ queryKey: ['drug-classes'] });
    },
  });
  const ok = name.trim().length >= 2;
  return (
    <form
      className="dc-add dc-add-group"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok) add.mutate();
      }}
    >
      <Input
        aria-label={`Name of a group to add to ${ingredientName}`}
        placeholder="e.g. Respiratory fluoroquinolones"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Button type="submit" size="sm" busy={add.isPending} disabled={!ok}>
        Add group
      </Button>
      {add.isError ? <Notice tone="error">Not added: {errorMessage(add.error)}</Notice> : null}
    </form>
  );
}
