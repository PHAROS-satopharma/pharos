import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { fetchAllPages, unwrap } from '../../lib/api';
import { useRegulators } from '../../lib/regulators';
import {
  MAX_LOOKBACK_DAYS,
  cairoWeekStart,
  lastLook,
  sinceFor,
  totalNew,
  type CardRegulator,
  type NewItem,
  type RegulatorPage,
} from './horizontal';

const FIVE_MIN = 5 * 60_000;

/** Her pages (regulator_page, 0032), in the order of her list. */
export function useRegulatorPages() {
  return useQuery({
    queryKey: ['regulator-pages'],
    staleTime: 10 * 60_000,
    queryFn: async () =>
      unwrap<RegulatorPage[] | null>(
        await supabase
          .from('regulator_page')
          .select('id,regulator_id,kind,sort,label,url,read_by,partial,note')
          .order('regulator_id')
          .order('sort'),
      ) ?? [],
  });
}

/** The signed-in person's last look at each authority. */
export function useMyLooks() {
  return useQuery({
    queryKey: ['my-country-look'],
    staleTime: FIVE_MIN,
    queryFn: async () => {
      const rows =
        unwrap<{ regulator_id: string; looked_at: string }[] | null>(
          await supabase.from('v_my_country_look').select('regulator_id,looked_at'),
        ) ?? [];
      return new Map(rows.map((r) => [r.regulator_id, r.looked_at]));
    },
  });
}

/** What the authorities published from `fromIso` to now (new_items, 0032), newest first. */
export function useNewItems(fromIso: string | null) {
  return useQuery({
    queryKey: ['new-items', fromIso],
    enabled: fromIso !== null,
    staleTime: FIVE_MIN,
    queryFn: () =>
      fetchAllPages<NewItem>(async (from, to) =>
        await supabase
          .rpc('new_items', { p_from: fromIso })
          .order('first_seen_at', { ascending: false })
          .order('document_id')
          .range(from, to),
      ),
  });
}

/** "Mark as looked at": stamps every authority of the country as the signed-in person. */
export function useMarkLooked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (regulatorId: string) =>
      unwrap<string>(await supabase.rpc('mark_country_looked', { p_regulator: regulatorId })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-country-look'] }),
  });
}

export interface HorizontalData {
  now: Date;
  weekStart: Date;
  regulators: CardRegulator[];
  looks: Map<string, string>;
  /** Everything from the earliest point any card or the week's figures need. */
  items: NewItem[];
  isPending: boolean;
  error: unknown;
}

/**
 * The items behind the Sources page and the "N new" mark beside its tab: from this week's Sunday (Cairo), or
 * from the earliest last look when that is older, never more than MAX_LOOKBACK_DAYS back.
 */
export function useHorizontal(): HorizontalData {
  // One clock per page visit, so the window does not move (and the query does not refetch) on every render.
  const [now] = useState(() => new Date());
  const weekStart = useMemo(() => cairoWeekStart(now), [now]);
  const regulators = useRegulators();
  const looks = useMyLooks();
  const fromIso = useMemo(() => {
    if (!looks.data || !regulators.data) return null;
    let from = weekStart;
    const floor = new Date(now.getTime() - MAX_LOOKBACK_DAYS * 86_400_000);
    for (const r of regulators.data) {
      const since = sinceFor(lastLook({ regulators: [r] }, looks.data), weekStart, now);
      if (since < from) from = since;
    }
    if (from < floor) from = floor;
    // to the hour: the tab's mark and the page share one query; the lists filter to the exact minute
    return new Date(Math.floor(from.getTime() / 3_600_000) * 3_600_000).toISOString();
  }, [looks.data, regulators.data, weekStart, now]);
  const items = useNewItems(fromIso);
  return {
    now,
    weekStart,
    regulators: regulators.data ?? [],
    looks: looks.data ?? new Map(),
    items: items.data ?? [],
    isPending: regulators.isPending || looks.isPending || items.isPending,
    error: regulators.error ?? looks.error ?? items.error ?? null,
  };
}

/** How many items are new since the person last looked, across every country (the tab's "N new"). */
export function countNew(data: HorizontalData): number {
  return totalNew(data.regulators, data.items, data.looks, data.weekStart, data.now);
}
