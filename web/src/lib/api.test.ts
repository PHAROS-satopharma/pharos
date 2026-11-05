import { describe, expect, it, vi } from 'vitest';

// api.ts imports the Supabase client; the helper under test never calls it.
vi.mock('./supabase', () => ({ supabase: {} }));

import { unwrapChanged } from './api';

describe('unwrapChanged', () => {
  it('treats an empty result as a refused change', () => {
    expect(() => unwrapChanged({ data: [], error: null }, 'this source')).toThrow(
      'You are not allowed to change this source, or it no longer exists.',
    );
  });

  it('treats a missing result as a refused change', () => {
    expect(() => unwrapChanged({ data: null, error: null }, 'this alert')).toThrow(
      'You are not allowed to change this alert, or it no longer exists.',
    );
  });

  it('returns the changed rows', () => {
    expect(unwrapChanged<{ id: string }>({ data: [{ id: 'ema-dhpc' }], error: null }, 'this source')).toEqual([
      { id: 'ema-dhpc' },
    ]);
  });

  it('throws the database error as it is', () => {
    expect(() => unwrapChanged({ data: null, error: { message: 'permission denied for table source' } }, 'this source')).toThrow(
      'permission denied for table source',
    );
  });
});
