import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { Tag } from '../../ui/Tag';

/**
 * Whether the label lists a coded reaction (mesh_listed, 0062): our label's 4.8, or else the reference product's
 * adverse reactions, naming it or a broader heading above it. Nothing is shown while no English label is coded.
 */
export function Listed({ ingredientId, ui }: { ingredientId: string | null; ui: string | null | undefined }) {
  const q = useQuery({
    queryKey: ['mesh-listed', ingredientId, ui] as const,
    enabled: Boolean(ingredientId && ui),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const [listed, coded] = await Promise.all([
        supabase.rpc('mesh_listed', { p_ingredient: ingredientId, p_ui: ui }),
        supabase.from('label_coded').select('source').eq('ingredient_id', ingredientId!),
      ]);
      return { listed: unwrap<string | null>(listed), labels: (unwrap<{ source: string }[] | null>(coded) ?? []).length };
    },
  });
  if (!ingredientId || !ui || !q.data || !q.data.labels) return null;
  if (q.data.listed === 'our_label')
    return (
      <Tag tone="success" title="Section 4.8 of our label names it, or a broader heading above it.">
        In our label
      </Tag>
    );
  if (q.data.listed === 'reference')
    return (
      <Tag tone="blue" title="Not found in our label; the reference product’s adverse reactions name it.">
        In the reference label
      </Tag>
    );
  return (
    <Tag tone="danger" title="Neither our label nor the reference label names it or a broader heading: it may be unexpected.">
      Not in our label
    </Tag>
  );
}
