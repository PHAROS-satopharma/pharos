import { describe, expect, it, vi } from 'vitest';

// queries.ts imports the Supabase client; the totals under test never call it.
vi.mock('../../lib/supabase', () => ({ supabase: {} }));

import { RUN_NOTE, totalsBySource, type RunSlice } from './queries';

function run(started_at: string, error: string | null, source_id = 'fda-email', http_status: number | null = null): RunSlice {
  return {
    source_id, started_at, finished_at: started_at, http_status,
    items_seen: 0, items_new: 0, items_matched: 0, error,
  } as RunSlice;
}

const HELD = 'imap: 1 message(s) held unread: sender not verified (no DMARC, DKIM or SPF pass) or too big';

describe('totalsBySource', () => {
  it('drops an older failure note once a later run is clean', () => {
    // newest first, as fetchRuns returns them: the 15:02 run read the mail the 11:07 run held
    const t = totalsBySource([run('2026-11-05T13:02:00Z', null), run('2026-11-05T09:07:00Z', HELD)]).get('fda-email');
    expect(t?.lastError).toBeNull();
    expect(t?.failed).toBe(0);           // held mail is a note on a completed run, as in source_run_failed()
    expect(t?.runs).toBe(2);
  });

  it('shows the note while the newest run is the one that failed', () => {
    const t = totalsBySource([run('2026-11-05T13:02:00Z', HELD), run('2026-11-05T09:07:00Z', null)]).get('fda-email');
    expect(t?.lastError).toBe(HELD);
  });

  it('does not count a backfill that stopped at its time budget as a failed run', () => {
    // Health Canada, 5 Nov 2026: six backfills stopped at 10 minutes with recalls left for the next run,
    // and the page said "6 of 11 runs failed" although every run read the list.
    const budget = (n: number) => `time budget reached: ${n} new item(s) wait for the next run`;
    const runs = [
      run('2026-11-05T19:17:00Z', null, 'hc-recalls', 200),
      run('2026-11-05T14:58:00Z', null, 'hc-recalls', 200),
      ...[28, 682, 1132, 1578, 2104, 91].map((n, i) => run(`2026-11-05T1${4 - Math.floor(i / 5)}:4${i}:00Z`, budget(n), 'hc-recalls', 200)),
    ];
    const t = totalsBySource(runs).get('hc-recalls');
    expect(t?.runs).toBe(8);
    expect(t?.failed).toBe(0);
    expect(t?.lastError).toBeNull();
  });

  it('does not count a run that stopped at its item cap as a failed run', () => {
    const t = totalsBySource([
      run('2026-11-06T10:00:00Z', 'item cap reached: 212 new item(s) wait for the next run', 'pubmed', 200),
    ]).get('pubmed');
    expect(t?.failed).toBe(0);
  });

  it('counts a real failure, and one bad notice in a completed run is only a note', () => {
    const t = totalsBySource([
      run('2026-11-05T19:20:00Z', "parse: no rows recognised at https://www.infarmed.pt/x (marker 'result-item' missing)", 'infarmed-circulares', 200),
      run('2026-11-05T16:20:00Z', '1 item(s) failed; first: infarmed:12659868: FetchError: HTTP 500', 'infarmed-circulares', 200),
      run('2026-11-05T13:33:00Z', null, 'fda-enforcement', 500),
    ]);
    expect(t.get('infarmed-circulares')?.failed).toBe(1);
    expect(t.get('infarmed-circulares')?.lastError).toMatch(/^parse: /);
    expect(t.get('fda-enforcement')?.failed).toBe(1);
  });
});

// The database decides what a failed run is (source_run_failed() in the migrations); this page decides
// it again for its 48-hour counts. The two lists of notes must stay one list.
const MIGRATIONS = import.meta.glob('../../../../supabase/migrations/*.sql', {
  query: '?raw', import: 'default', eager: true,
}) as Record<string, string>;

describe('RUN_NOTE', () => {
  it('is the same list of notes as source_run_failed() in the database', () => {
    const defining = Object.keys(MIGRATIONS).sort()
      .filter((f) => /function\s+(public\.)?source_run_failed/i.test(MIGRATIONS[f]));
    expect(defining.length).toBeGreaterThan(0);
    const sql = MIGRATIONS[defining[defining.length - 1]];
    const inDb = /p_error\s+!~\s+'([^']+)'/.exec(sql)?.[1];
    expect(inDb).toBeDefined();
    expect(RUN_NOTE.source).toBe(inDb);
  });
});
