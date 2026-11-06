import { describe, expect, it } from 'vitest';
import { matchPath } from 'react-router-dom';
import { HOME, REMOVED_PATHS, tabsFor } from './nav';

const removed = (pathname: string) => REMOVED_PATHS.some((p) => matchPath({ path: p }, pathname) !== null);

describe('tabsFor', () => {
  it('gives everyone the three screening tabs, in her order, then Cases', () => {
    expect(tabsFor(false).map((t) => t.label)).toEqual(['Ingredients', 'Sources', 'Reports', 'Cases']);
    expect(tabsFor(false).map((t) => t.to)).toEqual(['/ingredients', '/sources', '/reports', '/cases']);
  });

  it('adds People, last, for the administrator who manages the people only', () => {
    expect(tabsFor(true).map((t) => t.label)).toEqual(['Ingredients', 'Sources', 'Reports', 'Cases', 'People']);
    expect(tabsFor(true)[4].to).toBe('/people');
    expect(tabsFor(false).some((t) => t.to === '/people')).toBe(false);
  });

  it('opens Ingredients at /, the first tab', () => {
    expect(HOME).toBe(tabsFor(false)[0].to);
  });

  it('never offers a removed screen', () => {
    for (const t of tabsFor(true)) expect(removed(t.to)).toBe(false);
  });
});

describe('REMOVED_PATHS', () => {
  it('takes every address of a removed screen, with or without an id', () => {
    for (const p of [
      '/notifications',
      '/issues',
      '/issue/3f2a6c1e-0b6d-4f0e-9d7a-2b1c0e5f4a11',
      '/issue/3f2a6c1e-0b6d-4f0e-9d7a-2b1c0e5f4a11/',
      '/signals',
      '/signals/12',
      '/oversight',
      '/psur',
      '/labels',
    ]) {
      expect(removed(p), p).toBe(true);
    }
  });

  it('leaves the screens that stay alone', () => {
    for (const p of ['/', '/ingredients', '/ingredients/42', '/sources', '/reports', '/people', '/me']) {
      expect(removed(p), p).toBe(false);
    }
  });
});
