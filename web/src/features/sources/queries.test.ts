import { describe, expect, it, vi } from 'vitest';

// queries.ts imports the Supabase client; the totals under test never call it.
vi.mock('../../lib/supabase', () => ({ supabase: {} }));

import { totalsBySource, type RunSlice } from './queries';

function run(started_at: string, error: string | null): RunSlice {
  return {
    source_id: 'fda-email', started_at, finished_at: started_at, http_status: null,
    items_seen: 0, items_new: 0, items_matched: 0, error,
  } as RunSlice;
}

const HELD = 'imap: 1 message(s) held unread: sender not verified (no DMARC, DKIM or SPF pass) or too big';

describe('totalsBySource', () => {
  it('drops an older failure note once a later run is clean', () => {
    // newest first, as fetchRuns returns them: the 15:02 run read the mail the 11:07 run held
    const t = totalsBySource([run('2026-11-05T13:02:00Z', null), run('2026-11-05T09:07:00Z', HELD)]).get('fda-email');
    expect(t?.lastError).toBeNull();
    expect(t?.failed).toBe(1);
    expect(t?.runs).toBe(2);
  });

  it('shows the note while the newest run is the one that failed', () => {
    const t = totalsBySource([run('2026-11-05T13:02:00Z', HELD), run('2026-11-05T09:07:00Z', null)]).get('fda-email');
    expect(t?.lastError).toBe(HELD);
  });
});
