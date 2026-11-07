/** What the label watch read for one ingredient, per database page (label_watch, 0091). */

export interface WatchError {
  product: string;
  national_id: string;
  error: string;
  at: string | null;
}

export interface WatchSource {
  source_id: string;
  enabled: boolean;
  health: string;
  products: number;
  labels_read: number;
  unread: number;
  waiting: number;
  errors: WatchError[];
  last_checked_at: string | null;
  latest_label_date: string | null;
  latest_change_at: string | null;
  listed_at: string | null;
  lists: number;
  lists_broken: number;
  gaps: string | null;
  last_run: { finished_at: string | null; error: string | null; failed: boolean } | null;
}

export interface WatchPage {
  page_id: string;
  regulator_id: string;
  regulator: string;
  country_name: string | null;
  country_code: string | null;
  label: string;
  url: string;
  note: string | null;
  partial: boolean;
  sources: WatchSource[];
}

/**
 * One page's state, worst first:
 * - blocked: no label source reads it (its note says why);
 * - off: its sources are switched off;
 * - failing: the last run of a source failed, or a source is blocked or degraded;
 * - not_run: no source has listed this ingredient yet;
 * - unread: a label could not be read, or a list broke off;
 * - read: listed to its end, every label read (some may wait for their turn: `waiting`).
 */
export type PageState = 'blocked' | 'off' | 'failing' | 'not_run' | 'unread' | 'read';

export function pageState(p: WatchPage): PageState {
  const on = p.sources.filter((s) => s.enabled);
  if (!p.sources.length) return 'blocked';
  if (!on.length) return 'off';
  if (on.some((s) => s.last_run?.failed || s.health === 'blocked' || s.health === 'degraded')) return 'failing';
  if (on.every((s) => !s.lists)) return 'not_run';
  if (on.some((s) => s.unread > 0 || s.lists_broken > 0)) return 'unread';
  return 'read';
}

/** The page's counts over its switched-on sources (a page may be read by two, e.g. Medsafe's two lists). */
export function pageTotals(p: WatchPage) {
  const on = p.sources.filter((s) => s.enabled);
  const max = (xs: (string | null)[]) => xs.filter((x): x is string => Boolean(x)).sort().at(-1) ?? null;
  return {
    products: on.reduce((n, s) => n + s.products, 0),
    labels_read: on.reduce((n, s) => n + s.labels_read, 0),
    unread: on.reduce((n, s) => n + s.unread, 0),
    waiting: on.reduce((n, s) => n + s.waiting, 0),
    errors: on.flatMap((s) => s.errors),
    gaps: on.map((s) => s.gaps).filter((g): g is string => Boolean(g)),
    latest_label_date: max(on.map((s) => s.latest_label_date)),
    latest_change_at: max(on.map((s) => s.latest_change_at)),
    listed_at: max(on.map((s) => s.listed_at)),
    run_error: on.map((s) => (s.last_run?.failed ? s.last_run.error : null)).find(Boolean) ?? null,
  };
}

/** The line above the table: pages read out of all, products found, labels unread. */
export function watchSummary(pages: WatchPage[]) {
  const states = pages.map(pageState);
  const totals = pages.map(pageTotals);
  return {
    pages: pages.length,
    read: states.filter((s) => s === 'read' || s === 'unread').length,
    blocked: states.filter((s) => s === 'blocked').length,
    failing: states.filter((s) => s === 'failing' || s === 'off').length,
    not_run: states.filter((s) => s === 'not_run').length,
    products: totals.reduce((n, t) => n + t.products, 0),
    unread: totals.reduce((n, t) => n + t.unread, 0),
  };
}

/** Pages in the order she reads them: those needing a look first, then by country. */
const ORDER: Record<PageState, number> = { failing: 0, off: 1, unread: 2, not_run: 3, read: 4, blocked: 5 };

export function sortPages(pages: WatchPage[]): WatchPage[] {
  return [...pages].sort(
    (a, b) =>
      ORDER[pageState(a)] - ORDER[pageState(b)] ||
      (a.country_name ?? a.regulator).localeCompare(b.country_name ?? b.regulator) ||
      a.label.localeCompare(b.label),
  );
}
