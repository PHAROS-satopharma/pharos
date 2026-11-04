import { supabase } from './supabase';

interface DbResult {
  data: unknown;
  error: { message: string } | null;
}

/** Turns a Supabase response into its data, or throws its error as a plain Error. */
export function unwrap<T>(res: DbResult): T {
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  try {
    return JSON.stringify(e);
  } catch {
    return 'Something went wrong.';
  }
}

/** Reads every page of a query that may return more than the API's 1,000-row ceiling. */
export async function fetchAllPages<T>(
  page: (from: number, to: number) => PromiseLike<DbResult>,
  size = 1000,
  max = 50000,
): Promise<T[]> {
  const out: T[] = [];
  for (let from = 0; from < max; from += size) {
    const rows = unwrap<T[] | null>(await page(from, from + size - 1)) ?? [];
    out.push(...rows);
    if (rows.length < size) break;
  }
  return out;
}

/** Calls an Edge Function and returns its JSON, with the function's own error message when it fails. */
export async function invoke<T>(name: string, body: Record<string, unknown>): Promise<T> {
  const { data, error } = await supabase.functions.invoke(name, { body });
  if (error) {
    let message = errorMessage(error);
    const ctx = (error as { context?: unknown }).context;
    if (ctx instanceof Response) {
      try {
        const j = (await ctx.clone().json()) as { error?: string; message?: string };
        message = j.error || j.message || message;
      } catch {
        // keep the generic message
      }
    }
    throw new Error(message);
  }
  return data as T;
}

/** A pre-signed link to an archived original (valid for ten minutes). */
export async function archiveUrl(r2Key: string): Promise<string> {
  const r = await invoke<{ url: string }>('archive-url', { r2_key: r2Key });
  if (!r || !r.url) throw new Error('The archive did not return a link.');
  return r.url;
}

/** Opens an archived original in a new tab. The tab is opened first so the browser does not block it. */
export async function openArchived(r2Key: string): Promise<void> {
  const w = window.open('about:blank', '_blank');
  try {
    const url = await archiveUrl(r2Key);
    if (w) {
      w.opener = null;
      w.location.href = url;
    } else {
      window.location.assign(url);
    }
  } catch (e) {
    w?.close();
    throw e;
  }
}

/** Escapes the wildcard characters of a LIKE pattern. */
export function escapeLike(s: string): string {
  return s.replace(/[\\%_]/g, (c) => `\\${c}`);
}
