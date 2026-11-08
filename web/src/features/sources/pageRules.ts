// Dr Sama edits her own pages (her feedback, 8 Nov 2026): add, change and remove a link on a country's card, and
// add a local reference (an authority with its first link). Pure helpers, no I/O; the writes are in PageEdit.tsx
// and run under regulator_page's admin policy (0032), every change in the audit log.

import type { PageKind, RegulatorPage } from './horizontal';

export const PAGE_KINDS: { value: PageKind; label: string }[] = [
  { value: 'safety', label: 'Safety notifications' },
  { value: 'dhpc', label: 'DHPC' },
  { value: 'database', label: 'Drug database' },
];

export interface PageDraft {
  regulator_id: string;
  kind: PageKind;
  label: string;
  url: string;
  note: string;
}

export const LABEL_MAX = 200;
export const NOTE_MAX = 1000;

/** The address as typed, or null when it is not a full http(s) address. */
export function cleanUrl(raw: string): string | null {
  const u = raw.trim();
  if (!u) return null;
  try {
    const parsed = new URL(u);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
    if (!parsed.hostname.includes('.')) return null;
    return u;
  } catch {
    return null;
  }
}

/** Two addresses that open the same page: case of the host, a trailing slash and a #part do not count. */
export function sameAddress(a: string, b: string): boolean {
  const norm = (s: string) => {
    try {
      const u = new URL(s.trim());
      u.hash = '';
      return `${u.protocol}//${u.host.toLowerCase()}${u.pathname.replace(/\/+$/, '')}${u.search}`;
    } catch {
      return s.trim().replace(/\/+$/, '');
    }
  };
  return norm(a) === norm(b);
}

/** Why the link cannot be saved, in her words; null when it can. `selfId` is the page being changed. */
export function checkPage(d: PageDraft, pages: RegulatorPage[], selfId?: string): string | null {
  if (!d.regulator_id) return 'Choose the authority.';
  const label = d.label.trim();
  if (!label) return 'Give the link a name, as it should appear in the list.';
  if (label.length > LABEL_MAX) return `Keep the name under ${LABEL_MAX} characters.`;
  const url = cleanUrl(d.url);
  if (!url) return 'That is not a web address. Paste the full link, starting with https://';
  if (d.note.trim().length > NOTE_MAX) return `Keep the note under ${NOTE_MAX} characters.`;
  const twin = pages.find((p) => p.id !== selfId && p.regulator_id === d.regulator_id && sameAddress(p.url, url));
  if (twin) return `This authority already has this link, as “${twin.label}”.`;
  return null;
}

/** The row written to regulator_page. read_by and partial are never set here: a link she adds is one she opens
 *  herself, and changing a link never changes what the app reads. */
export function pageRow(d: PageDraft) {
  const note = d.note.trim();
  return {
    regulator_id: d.regulator_id,
    kind: d.kind,
    label: d.label.trim(),
    url: (cleanUrl(d.url) ?? d.url).trim(),
    note: note || null,
  };
}

/** A new link goes last in its authority's list. */
export function nextSort(pages: RegulatorPage[], regulatorId: string): number {
  return pages.filter((p) => p.regulator_id === regulatorId).reduce((m, p) => Math.max(m, p.sort), 0) + 1;
}

/** Changing the address of a page the app reads does not move the app's reader: say so before she saves. */
export function readerWarning(page: Pick<RegulatorPage, 'read_by' | 'url'>, newUrl: string): string | null {
  if (page.read_by.length === 0 || sameAddress(page.url, newUrl)) return null;
  return 'The app reads this page through its own reader. The new address changes the link in your list; what the app reads stays the same until the reader is changed too.';
}

// ───────────────────────────── a new local reference ─────────────────────────────

export interface AuthorityDraft {
  country_name: string;
  country_code: string;
  name: string;
  short: string;
}

/** Why the authority cannot be added; null when it can. */
export function checkAuthority(a: AuthorityDraft, takenIds: Set<string>): string | null {
  if (!a.country_name.trim()) return 'Write the country.';
  if (!/^[A-Za-z]{2}$/.test(a.country_code.trim())) return 'The country code is two letters, as on its flag: SA, AE, EG.';
  if (!a.name.trim()) return 'Write the authority’s name.';
  const id = authorityId(a.short || a.name);
  if (!id) return 'Give the authority a short name in Latin letters, such as EDA.';
  if (takenIds.has(id)) return `An authority called ${id} is already in PHAROS. Choose it from the list instead.`;
  return null;
}

/** The regulator id for a short name: capitals, digits and underscores, as the catalogue writes them. */
export function authorityId(short: string): string {
  return short
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 24);
}

/** The regulator row for a new authority. Languages matter only once a reader is added (Add a source sets the
 *  reader's own); English until then. */
export function authorityRow(a: AuthorityDraft) {
  return {
    id: authorityId(a.short || a.name),
    country_code: a.country_code.trim().toUpperCase(),
    country_name: a.country_name.trim(),
    name: a.name.trim(),
    languages: ['en'],
  };
}
