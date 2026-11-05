import { supabase } from './supabase';
import { downloadBlob } from './download';

interface DbResult {
  data: unknown;
  error: { message: string } | null;
}

/** Turns a Supabase response into its data, or throws its error as a plain Error. */
export function unwrap<T>(res: DbResult): T {
  if (res.error) throw new Error(res.error.message);
  return res.data as T;
}

/**
 * Like unwrap, for an update or delete chained with .select(…). Row-level security does not raise an error
 * when it refuses an update or delete: the statement simply touches no rows. An empty result is therefore
 * a refusal (or a row that has gone), and is thrown as one so the screen does not show success.
 */
export function unwrapChanged<T = unknown>(res: DbResult, what: string): T[] {
  if (res.error) throw new Error(res.error.message);
  const rows = Array.isArray(res.data) ? (res.data as T[]) : [];
  if (rows.length === 0) throw new Error(`You are not allowed to change ${what}, or it no longer exists.`);
  return rows;
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

/**
 * Saves an archived original under its real name. The file is fetched here and saved by the browser,
 * so no empty tab is left behind and a spreadsheet is not lost to a blocked pop-up download.
 */
export async function downloadArchived(r2Key: string, filename: string): Promise<void> {
  const url = await archiveUrl(r2Key);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`The archive answered ${res.status}.`);
  downloadBlob(await res.blob(), filename);
}

/**
 * Escapes the wildcard characters of a LIKE pattern. The API also reads `*` as `%` and offers no escape
 * for it, so a typed `*` becomes `_` (exactly one character, which includes a real `*`) and never
 * matches every title.
 */
export function escapeLike(s: string): string {
  return s.replace(/[\\%_]/g, (c) => `\\${c}`).replace(/\*/g, '_');
}
