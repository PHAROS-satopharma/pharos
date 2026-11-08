import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { PRODUCT_SELECT, toProduct, type ProductRaw } from './productForm';

export const PRODUCTS_KEY = ['products'] as const;

/** Every product on the list (archived ones too: a case may name one), with its ingredients and strengths. */
export function useProducts() {
  return useQuery({
    queryKey: PRODUCTS_KEY,
    queryFn: async () =>
      unwrap<ProductRaw[]>(await supabase.from('product').select(PRODUCT_SELECT).order('name')).map(toProduct),
    staleTime: 5 * 60 * 1000,
  });
}
