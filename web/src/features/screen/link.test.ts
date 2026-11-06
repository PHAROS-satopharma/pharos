import { describe, expect, it } from 'vitest';
import { FEED_URL } from '../sources/horizontal';

// The Ingredients screen and the Sources screen open the same page for a notice: document_link() in the
// database. Its feed rule must stay the one the web app uses to hide feeds.
const MIGRATIONS = import.meta.glob('../../../../supabase/migrations/*.sql', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** The newest migration whose text matches `re`. */
function latest(re: RegExp): string | undefined {
  return Object.keys(MIGRATIONS)
    .sort()
    .filter((f) => re.test(MIGRATIONS[f]))
    .pop();
}

describe('document_link', () => {
  it('hides a feed with the same rule as the web app', () => {
    const file = latest(/function\s+document_link\s*\(/);
    expect(file).toBeDefined();
    const inDb = /when d\.url ~\* '([^']+)' then\s+coalesce\(s\.page_url/.exec(MIGRATIONS[file as string])?.[1];
    expect(inDb).toBeDefined();
    expect(FEED_URL.source.replace(/\\\//g, '/')).toBe(inDb);
  });

  it('is what new_items() links to', () => {
    const file = latest(/function\s+new_items\s*\(/);
    expect(file).toBeDefined();
    const body = MIGRATIONS[file as string].split(/function\s+new_items\s*\(/)[1];
    expect(body).toMatch(/document_link\(d,\s*s,\s*r\)/);
  });
});
