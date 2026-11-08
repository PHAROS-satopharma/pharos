import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { Tag } from '../../ui/Tag';

/**
 * Whether the label lists a coded reaction (mesh_listed, 0062): our label's 4.8, or else the reference product's
 * adverse reactions, naming it or a broader heading above it. Nothing is shown while no English label is coded.
 */
export function Listed({
  ingredientId,
  ui,
  who = null,
}: {
  ingredientId: string | null;
  ui: string | null | undefined;
  /** The ingredient's name, before the words, when a product's case shows one tag per ingredient (0099). */
  who?: string | null;
}) {
  const by = who ? `${who}: ` : '';
  const q = useQuery({
    queryKey: ['mesh-listed', ingredientId, ui] as const,
    enabled: Boolean(ingredientId && ui),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const [listed, coded] = await Promise.all([
        supabase.rpc('mesh_listed', { p_ingredient: ingredientId, p_ui: ui }),
        supabase.from('label_coded').select('source').eq('ingredient_id', ingredientId!),
      ]);
      const rows = unwrap<{ source: string }[] | null>(coded) ?? [];
      return {
        listed: unwrap<string | null>(listed),
        labels: rows.length,
        ours: rows.some((r) => r.source === 'our_label'),
      };
    },
  });
  if (!ingredientId || !ui || !q.data || !q.data.labels) return null;
  if (q.data.listed === 'our_label')
    return (
      <Tag tone="success" title="Section 4.8 of our label names it, or a broader heading above it.">
        {by}In our label
      </Tag>
    );
  if (q.data.listed === 'reference')
    return (
      <Tag tone="blue" title="Not found in our label; the reference product’s adverse reactions name it.">
        {by}In the reference label
      </Tag>
    );
  // "Not in our label" only when our label was read; with the reference label alone, say that one
  if (!q.data.ours)
    return (
      <Tag
        tone="danger"
        title="The reference product’s adverse reactions do not name it or a broader heading. No label of ours in English is read."
      >
        {by}Not in the reference label
      </Tag>
    );
  return (
    <Tag tone="danger" title="Neither our label nor the reference label names it or a broader heading: it may be unexpected.">
      {by}Not in our label
    </Tag>
  );
}
