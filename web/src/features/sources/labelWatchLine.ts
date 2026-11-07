import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import type { WatchSource } from '../screen/labelWatch';

/** Every label source's counts over all ingredients (label_watch_sources, 0091), for the database pages. */
export function useLabelWatchSources() {
  return useQuery({
    queryKey: ['label-watch-sources'],
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<Record<string, WatchSource> | null>(await supabase.rpc('label_watch_sources')) ?? {},
  });
}

/**
 * One line under a database page on the Sources page: what the weekly label watch read there over every
 * ingredient, or null when no label source reads it (its note already says why).
 */
export function watchLine(readBy: string[], bySource: Record<string, WatchSource>): string | null {
  const on = readBy.map((id) => bySource[id]).filter((s): s is WatchSource => Boolean(s?.enabled));
  if (!on.length) return null;
  const sum = (k: 'products' | 'labels_read' | 'unread' | 'lists' | 'lists_broken') =>
    on.reduce((n, s) => n + s[k], 0);
  if (!sum('lists')) return 'Label watch: not read yet for our ingredients.';
  const parts = [
    `${sum('products')} ${sum('products') === 1 ? 'product' : 'products'} of our ingredients`,
    `${sum('labels_read')} ${sum('labels_read') === 1 ? 'label' : 'labels'} read`,
  ];
  if (sum('unread')) parts.push(`${sum('unread')} unread`);
  if (sum('lists_broken')) {
    parts.push(`${sum('lists_broken')} of ${sum('lists')} lists broke off`);
  }
  const failed = on.find((s) => s.last_run?.failed);
  if (failed) parts.push(`last run failed: ${failed.last_run?.error ?? 'no reason given'}`);
  return `Label watch: ${parts.join(' · ')}.`;
}
