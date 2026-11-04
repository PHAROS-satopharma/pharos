import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { unwrap } from '../../lib/api';

export function useIngredientList() {
  return useQuery({
    queryKey: ['ingredient-list'],
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<{ id: string; inn_en: string }[] | null>(
        await supabase.from('ingredient').select('id,inn_en').eq('active', true).order('inn_en'),
      ) ?? [],
  });
}
