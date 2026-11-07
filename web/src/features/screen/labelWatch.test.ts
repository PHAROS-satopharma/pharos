import { describe, expect, it } from 'vitest';
import { pageState, pageTotals, sortPages, watchSummary, type WatchPage, type WatchSource } from './labelWatch';

function src(over: Partial<WatchSource> = {}): WatchSource {
  return {
    source_id: 'spc-x',
    enabled: true,
    health: 'ok',
    products: 3,
    labels_read: 3,
    unread: 0,
    waiting: 0,
    errors: [],
    last_checked_at: '2026-11-09T03:30:00Z',
    latest_label_date: '2026-10-01',
    latest_change_at: null,
    listed_at: '2026-11-09T03:23:00Z',
    lists: 1,
    lists_broken: 0,
    gaps: null,
    last_run: { finished_at: '2026-11-09T04:00:00Z', error: null, failed: false },
    ...over,
  };
}

function page(label: string, sources: WatchSource[], over: Partial<WatchPage> = {}): WatchPage {
  return {
    page_id: label,
    regulator_id: 'R',
    regulator: 'Agency',
    country_name: 'Spain',
    country_code: 'ES',
    label,
    url: 'https://example.test/',
    note: null,
    partial: false,
    sources,
    ...over,
  };
}

describe('the state of a database page', () => {
  it('is not read when no label source reads it', () => {
    expect(pageState(page('TGA', []))).toBe('blocked');
  });
  it('fails when its last run failed or its source is blocked', () => {
    expect(pageState(page('A', [src({ last_run: { finished_at: null, error: 'no label read', failed: true } })]))).toBe(
      'failing',
    );
    expect(pageState(page('B', [src({ health: 'blocked' })]))).toBe('failing');
  });
  it('is switched off when every source of it is', () => {
    expect(pageState(page('A', [src({ enabled: false })]))).toBe('off');
  });
  it('is not read yet before any list of the ingredient', () => {
    expect(pageState(page('A', [src({ lists: 0, products: 0, labels_read: 0 })]))).toBe('not_run');
  });
  it('is read with gaps when a label is unread or a list broke off', () => {
    expect(pageState(page('A', [src({ unread: 1 })]))).toBe('unread');
    expect(pageState(page('B', [src({ lists_broken: 1, gaps: 'page 2: HTTP 503' })]))).toBe('unread');
  });
  it('is read when listed to its end and nothing is unread', () => {
    expect(pageState(page('A', [src()]))).toBe('read');
  });
});

describe('the counts of a page and of the list', () => {
  it('adds the switched-on sources of one page and keeps the newest dates', () => {
    const t = pageTotals(
      page('Medsafe', [
        src({ products: 2, labels_read: 1, waiting: 1, latest_label_date: '2025-01-01' }),
        src({ products: 4, labels_read: 4, latest_change_at: '2026-11-09T04:00:00Z' }),
        src({ enabled: false, products: 99 }),
      ]),
    );
    expect(t).toMatchObject({ products: 6, labels_read: 5, waiting: 1, latest_label_date: '2026-10-01' });
    expect(t.latest_change_at).toBe('2026-11-09T04:00:00Z');
  });
  it('counts pages read, not read and failing, and the unread labels', () => {
    const pages = [
      page('A', [src()]),
      page('B', [src({ unread: 2 })]),
      page('C', []),
      page('D', [src({ last_run: { finished_at: null, error: 'x', failed: true } })]),
    ];
    expect(watchSummary(pages)).toMatchObject({ pages: 4, read: 2, blocked: 1, failing: 1, unread: 2, products: 9 });
  });
  it('puts the pages that need a look first and those not read last', () => {
    const pages = [
      page('Read', [src()], { country_name: 'Austria' }),
      page('Blocked', [], { country_name: 'Australia' }),
      page('Failing', [src({ last_run: { finished_at: null, error: 'x', failed: true } })], { country_name: 'Spain' }),
    ];
    expect(sortPages(pages).map((p) => p.label)).toEqual(['Failing', 'Read', 'Blocked']);
  });
});
