import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from './supabase';
import { unwrap } from './api';
import { regionName } from './labels';
import type { Regulator } from './types';

export function useRegulators() {
  return useQuery({
    queryKey: ['regulators'],
    staleTime: 10 * 60_000,
    queryFn: async () =>
      unwrap<Regulator[]>(
        await supabase
          .from('regulator')
          .select('id,country_code,country_name,name,languages,homepage')
          .order('country_name')
          .order('name'),
      ),
  });
}

export interface CountryIndex {
  /** Country names that have a regulator, A to Z. */
  names: string[];
  codeOf: (name: string | null | undefined) => string | null;
  nameOf: (code: string | null | undefined) => string;
  /** Every language a regulator publishes in. */
  languages: string[];
}

/** Country names and codes as the regulator table writes them (the view gives names, flags need codes). */
export function useCountryIndex(): CountryIndex {
  const q = useRegulators();
  return useMemo<CountryIndex>(() => {
    const byName = new Map<string, string>();
    const byCode = new Map<string, string>();
    const langs = new Set<string>();
    for (const r of q.data ?? []) {
      if (!byName.has(r.country_name)) byName.set(r.country_name, r.country_code);
      if (!byCode.has(r.country_code.toUpperCase())) byCode.set(r.country_code.toUpperCase(), r.country_name);
      for (const l of r.languages ?? []) langs.add(l);
    }
    return {
      names: [...byName.keys()].sort((a, b) => a.localeCompare(b)),
      codeOf: (name) => (name ? byName.get(name) ?? null : null),
      nameOf: (code) => (code ? byCode.get(code.toUpperCase()) ?? regionName(code) : ''),
      languages: [...langs].sort(),
    };
  }, [q.data]);
}
