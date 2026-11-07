import { describe, expect, it } from 'vitest';
import type { WatchSource } from '../screen/labelWatch';
import { watchLine } from './labelWatchLine';

function src(over: Partial<WatchSource> = {}): WatchSource {
  return {
    source_id: 'spc-x',
    enabled: true,
    health: 'ok',
    products: 12,
    labels_read: 10,
    unread: 0,
    waiting: 2,
    errors: [],
    last_checked_at: null,
    latest_label_date: null,
    latest_change_at: null,
    listed_at: '2026-11-09T03:23:00Z',
    lists: 4,
    lists_broken: 0,
    gaps: null,
    last_run: { finished_at: null, error: null, failed: false },
    ...over,
  };
}

describe('the label-watch line of a database page', () => {
  it('is absent when no label source reads the page', () => {
    expect(watchLine([], { 'spc-x': src() })).toBeNull();
    expect(watchLine(['spc-x'], { 'spc-x': src({ enabled: false }) })).toBeNull();
  });
  it('says so before the first list', () => {
    expect(watchLine(['spc-x'], { 'spc-x': src({ lists: 0 }) })).toBe('Label watch: not read yet for our ingredients.');
  });
  it('counts products and labels read, and names what is wrong', () => {
    expect(watchLine(['spc-x'], { 'spc-x': src() })).toBe('Label watch: 12 products of our ingredients · 10 labels read.');
    expect(
      watchLine(['spc-x', 'spc-y'], {
        'spc-x': src({ unread: 1, lists_broken: 1 }),
        'spc-y': src({ products: 1, labels_read: 1, lists: 1, last_run: { finished_at: null, error: 'no label read', failed: true } }),
      }),
    ).toBe(
      'Label watch: 13 products of our ingredients · 11 labels read · 1 unread · 1 of 5 lists broke off · ' +
        'last run failed: no label read.',
    );
  });
});
