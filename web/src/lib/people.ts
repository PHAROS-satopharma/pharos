import { supabase } from './supabase';
import { unwrap } from './api';

/**
 * Names of people by id, read from person_directory (id, full name, role, active — never an email address
 * or a Telegram chat id). Every signed-in person may read it; the person table itself shows only your own
 * row unless you are an admin.
 */
export async function personNames(ids: ReadonlyArray<string | null | undefined>): Promise<Map<string, string>> {
  const unique = Array.from(new Set(ids.filter((x): x is string => typeof x === 'string' && x !== '')));
  const names = new Map<string, string>();
  for (let i = 0; i < unique.length; i += 200) {
    const rows =
      unwrap<{ id: string; full_name: string }[] | null>(
        await supabase.from('person_directory').select('id,full_name').in('id', unique.slice(i, i + 200)),
      ) ?? [];
    for (const r of rows) names.set(r.id, r.full_name);
  }
  return names;
}
