import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';
import { personNames } from '../../lib/people';

export interface OurLabel {
  id: string;
  ingredient_id: string;
  product_name: string;
  version: string;
  lang: string;
  sections: Record<string, string>;
  file_name: string | null;
  uploaded_at: string;
  superseded_at: string | null;
  ingredient: { inn_en: string } | null;
  uploaded_by_name: string | null;
}

/** Every saved version of our labels, newest first; names from person_directory. */
export function useOurLabels() {
  return useQuery({
    queryKey: ['our-labels'],
    queryFn: async () => {
      const rows =
        unwrap<(Omit<OurLabel, 'uploaded_by_name'> & { uploaded_by: string })[] | null>(
          await supabase
            .from('our_label')
            .select('id,ingredient_id,product_name,version,lang,sections,file_name,uploaded_at,superseded_at,uploaded_by,ingredient:ingredient_id(inn_en)')
            .order('uploaded_at', { ascending: false }),
        ) ?? [];
      const names = await personNames(rows.map((r) => r.uploaded_by));
      return rows.map(({ uploaded_by, ...r }): OurLabel => ({ ...r, uploaded_by_name: names.get(uploaded_by) ?? null }));
    },
  });
}

/** The current version of our labels for these ingredients (for a label-change notice). */
export function useCurrentLabels(ingredientIds: string[]) {
  return useQuery({
    queryKey: ['our-labels', 'current', ingredientIds],
    enabled: ingredientIds.length > 0,
    queryFn: async () =>
      unwrap<Pick<OurLabel, 'id' | 'ingredient_id' | 'product_name' | 'version' | 'lang' | 'sections' | 'uploaded_at'>[] | null>(
        await supabase
          .from('our_label')
          .select('id,ingredient_id,product_name,version,lang,sections,uploaded_at')
          .in('ingredient_id', ingredientIds)
          .is('superseded_at', null)
          .order('product_name'),
      ) ?? [],
  });
}
