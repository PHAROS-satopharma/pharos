// Literature references, Global and Local (Dr Sama, 8 Nov 2026; migration 0101). Pure helpers, no I/O: the
// wording of each line, the week's Cairo days, and the rules of the Add/Change form. The reads and writes are in
// LiteratureRefs.tsx and run under literature_ref's admin policy and record_literature_check() (0101).

import { cleanUrl, sameAddress } from './pageRules';

export type RefScope = 'global' | 'local';

/** One literature reference, as literature_ref holds it. */
export interface LiteratureRef {
  id: string;
  scope: RefScope;
  name: string;
  url: string | null;
  searched_in: string[];
  journal_like: string | null;
  note: string | null;
  sort: number;
  active: boolean;
}

/** The latest hand check in the days asked for. */
export interface RefCheck {
  result: 'nothing' | 'found';
  note: string | null;
  checked_at: string;
  checked_by: string;
}

/** One reference in literature_refs_week(): the days' searches, papers and hand check. */
export interface RefWeek {
  id: string;
  scope: RefScope;
  name: string;
  url: string | null;
  note: string | null;
  by_hand: boolean;
  searched_in: string[];
  journal_like: string | null;
  searches: number;
  last_searched: string | null;
  hits: number;
  /** The ingredient's papers these databases found; null with no ingredient, or for a hand-checked one. */
  found: number | null;
  check: RefCheck | null;
}

export const SCOPE_TITLE: Record<RefScope, string> = { global: 'Global', local: 'Local' };
export const SCOPE_EXPLAIN: Record<RefScope, string> = {
  global: 'The international literature databases.',
  local: 'The Egyptian medical journals the Egyptian Drug Authority asks for.',
};

const cairoDay = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Africa/Cairo',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

/** The Cairo calendar day of an instant, as yyyy-mm-dd. */
export function cairoIsoDay(at: Date): string {
  return cairoDay.format(at);
}

/** Sunday to Saturday, as the database's p_from and p_to, for the week that starts at `weekStart`. */
export function weekDays(weekStart: Date): { from: string; to: string } {
  const from = cairoIsoDay(weekStart);
  const [y, m, d] = from.split('-').map(Number);
  const to = new Date(Date.UTC(y, m - 1, d + 6)).toISOString().slice(0, 10);
  return { from, to };
}

type When = (iso: string) => string;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** How the reference was screened in those days, in her words; `period` is "this week", "these days" …. */
export function refStatus(r: RefWeek, when: When, period = 'this week'): { text: string; tone: 'ok' | 'warning' | 'danger' } {
  if (!r.by_hand) {
    if (r.searches === 0) return { text: `Searched by the app — no search recorded ${period} yet`, tone: 'warning' };
    const last = r.last_searched ? `, last ${when(r.last_searched)}` : '';
    return { text: `Searched by the app — ${plural(r.searches, 'search', 'searches')} ${period}${last}`, tone: 'ok' };
  }
  if (!r.check) return { text: `Checked by hand — not checked ${period}`, tone: 'danger' };
  const who = `${r.check.checked_by}, ${when(r.check.checked_at)}`;
  return r.check.result === 'nothing'
    ? { text: `Checked by hand — ${who}: nothing found`, tone: 'ok' }
    : { text: `Checked by hand — ${who}: found${r.check.note ? ` — ${r.check.note}` : ''}`, tone: 'warning' };
}

/** What was found for one ingredient: "Nothing found", "3 papers", or the hand check's answer. */
export function refFound(r: RefWeek): string {
  if (r.by_hand) {
    if (!r.check) return 'Not checked';
    return r.check.result === 'nothing' ? 'Nothing found' : 'Found';
  }
  if (r.found === null) return '';
  return r.found === 0 ? 'Nothing found' : plural(r.found, 'paper', 'papers');
}

export interface RefDraft {
  scope: RefScope;
  name: string;
  url: string;
  note: string;
}

export const REF_NAME_MAX = 200;
export const REF_NOTE_MAX = 1000;

/** Why the reference cannot be saved, in her words; null when it can. `selfId` is the one being changed. */
export function checkRef(d: RefDraft, refs: LiteratureRef[], selfId?: string): string | null {
  const name = d.name.trim();
  if (!name) return 'Give the reference a name, as it should appear in the list.';
  if (name.length > REF_NAME_MAX) return `Keep the name under ${REF_NAME_MAX} characters.`;
  const url = cleanUrl(d.url);
  if (!url) return 'That is not a web address. Paste the full link, starting with https://';
  if (url.length > 500) return 'That address is too long.';
  if (d.note.trim().length > REF_NOTE_MAX) return `Keep the note under ${REF_NOTE_MAX} characters.`;
  const same = refs.filter((r) => r.active && r.scope === d.scope && r.id !== selfId);
  if (same.some((r) => r.name.trim().toLowerCase() === name.toLowerCase())) {
    return `${name} is already in the ${SCOPE_TITLE[d.scope]} list.`;
  }
  const twin = same.find((r) => r.url && sameAddress(r.url, url));
  if (twin) return `That address is already in the list, as ${twin.name}.`;
  return null;
}

/** The row literature_ref is written with. A reference she adds is checked by hand. */
export function refRow(d: RefDraft): { scope: RefScope; name: string; url: string; note: string | null } {
  return { scope: d.scope, name: d.name.trim(), url: (cleanUrl(d.url) ?? d.url).trim(), note: d.note.trim() || null };
}

/** After the last of its list. */
export function nextRefSort(refs: LiteratureRef[], scope: RefScope): number {
  return Math.max(0, ...refs.filter((r) => r.scope === scope).map((r) => r.sort)) + 10;
}
