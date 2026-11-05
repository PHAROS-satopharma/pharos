/**
 * A link scraped from a regulator's site (or typed by a person) as an href, only when it is an absolute
 * http(s) address. Anything else — javascript:, data:, file:, a relative path, garbage — gives null, and the
 * caller shows plain text instead of a link.
 */
export function safeHref(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null;
  const s = url.trim();
  if (!s) return null;
  let u: URL;
  try {
    u = new URL(s);
  } catch {
    return null;
  }
  return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : null;
}
