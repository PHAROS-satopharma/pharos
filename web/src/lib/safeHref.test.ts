import { describe, expect, it } from 'vitest';
import { safeHref } from './safeHref';

describe('safeHref', () => {
  it('keeps absolute http and https addresses', () => {
    expect(safeHref('https://www.ema.europa.eu/en/news')).toBe('https://www.ema.europa.eu/en/news');
    expect(safeHref('http://example.test/a?b=1#c')).toBe('http://example.test/a?b=1#c');
    expect(safeHref('  https://example.test/x  ')).toBe('https://example.test/x');
    expect(safeHref('HTTPS://Example.test/')).toBe('https://example.test/');
  });

  it('refuses every other scheme', () => {
    expect(safeHref('javascript:alert(1)')).toBeNull();
    expect(safeHref(' JavaScript:alert(1)')).toBeNull();
    expect(safeHref('java\tscript:alert(1)')).toBeNull();
    expect(safeHref('data:text/html,<script>alert(1)</script>')).toBeNull();
    expect(safeHref('vbscript:msgbox(1)')).toBeNull();
    expect(safeHref('file:///etc/passwd')).toBeNull();
    expect(safeHref('mailto:someone@example.test')).toBeNull();
  });

  it('refuses relative paths, empty values and garbage', () => {
    expect(safeHref('/en/news')).toBeNull();
    expect(safeHref('//evil.example/x')).toBeNull();
    expect(safeHref('')).toBeNull();
    expect(safeHref('   ')).toBeNull();
    expect(safeHref(null)).toBeNull();
    expect(safeHref(undefined)).toBeNull();
    expect(safeHref('not a url')).toBeNull();
  });
});
