// The readiness line under an ingredient's name on the Ingredients page: Ready, or what is still running or
// still to come, with the facts she needs under it (ingredient_readiness(), migration 0045).
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { Tag } from '../../ui/Tag';
import { readinessItems, readinessNotes, type Readiness as ReadinessData } from './readiness';
import '../../styles/readiness.css';

export function Readiness({ ingredientId, active }: { ingredientId: string; active: boolean }) {
  const q = useQuery({
    queryKey: ['ingredient-readiness', ingredientId],
    enabled: active,
    staleTime: 60_000,
    queryFn: async () =>
      unwrap<ReadinessData>(await supabase.rpc('ingredient_readiness', { p_ingredient: ingredientId })),
  });
  if (!active) return null;
  if (q.isPending) return <span className="readiness readiness-loading">Reading how far it is prepared…</span>;
  if (q.isError || !q.data) return <span className="readiness readiness-loading">Readiness could not be read.</span>;

  const r = q.data;
  const items = readinessItems(r);
  const notes = readinessNotes(r);
  return (
    <span className="readiness">
      {items.length === 0 && r.ready ? (
        <Tag tone="success">Ready</Tag>
      ) : (
        <span className="readiness-wait">
          <span className="readiness-marker" aria-hidden />
          Still preparing: {items.join(' · ')}
        </span>
      )}
      {notes.length > 0 ? <span className="readiness-notes">{notes.join(' · ')}</span> : null}
    </span>
  );
}
