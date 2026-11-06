// The horizontal pass (Dr Sama's review, 6 Nov 2026): one card per country with the pages she checks, what
// the authorities published since she last looked, and the week's reading figures. Pure helpers, no I/O.

import { CAIRO, cairoMidnightUtc } from '../../lib/format';
import { KIND_LABEL, hostOf } from '../../lib/labels';
import type { DocType, Regulator, SourceChannel, SourceKind } from '../../lib/types';

export type PageKind = 'database' | 'dhpc' | 'safety';

/** One of her pages (table regulator_page, 0032). */
export interface RegulatorPage {
  id: string;
  regulator_id: string;
  kind: PageKind;
  sort: number;
  label: string;
  url: string;
  /** The app sources that read the page; empty = she opens it herself. */
  read_by: string[];
  partial: boolean;
  note: string | null;
}

/** One row of new_items(p_from, p_to). */
export interface NewItem {
  document_id: string;
  source_id: string;
  regulator_id: string;
  regulator_name: string;
  country_name: string;
  country_code: string;
  source_kind: SourceKind;
  title_orig: string;
  lang: string | null;
  /** A page a person can open; null for an e-mail with no web page. */
  link: string | null;
  published_date: string | null;
  first_seen_at: string;
  doc_type: DocType;
  matched: boolean;
  r2_key: string | null;
  mime: string | null;
  email_id: string | null;
  email_r2_key: string | null;
}

/** The fields of a source the cards need. */
export interface CardSource {
  id: string;
  regulator_id: string;
  kind: SourceKind;
  channel: SourceChannel;
  url: string;
  page_url: string | null;
  enabled: boolean;
}

export type CardRegulator = Pick<Regulator, 'id' | 'name' | 'country_code' | 'country_name' | 'homepage'>;

export interface CountryCard<S extends CardSource = CardSource> {
  country: string;
  code: string | null;
  regulators: CardRegulator[];
  /** Her pages, in the order of her list. */
  pages: RegulatorPage[];
  /** Every source of the country's authorities. */
  sources: S[];
}

export const OTHER_AUTHORITIES = 'Other authorities';
/** "New since you last looked" reaches back at most this far, so a country never looked at stays readable. */
export const MAX_LOOKBACK_DAYS = 31;
/** Never shown as a link outside Technical details: the same rule as new_items() in 0032 and
 *  tests/test_regulator_pages.py. */
export const FEED_URL = /(\.(xml|json|rss|atom)([?#]|$)|\/(rss|feed|atom)(\/|[?#]|$)|^https?:\/\/api\.)/i;

export function isFeedUrl(url: string | null | undefined): boolean {
  return Boolean(url) && FEED_URL.test(url as string);
}

const cairoDayParts = new Intl.DateTimeFormat('en-CA', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  timeZone: CAIRO,
});

/** Sunday 00:00 in Cairo of the week that holds `now` (weeks run Sunday to Saturday, Cairo time). */
export function cairoWeekStart(now: Date = new Date()): Date {
  const parts = cairoDayParts.formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  const y = get('year');
  const m = get('month');
  const d = get('day');
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday, of the Cairo calendar day
  return cairoMidnightUtc(y, m, d - weekday);
}

/**
 * One card per country: the countries of her list first, A to Z (the European Union among them), then every
 * other country that has a source, under "Other authorities".
 */
export function countryCards<S extends CardSource>(
  regulators: CardRegulator[],
  pages: RegulatorPage[],
  sources: S[],
): { hers: CountryCard<S>[]; others: CountryCard<S>[] } {
  const byCountry = new Map<string, CountryCard<S>>();
  const regById = new Map(regulators.map((r) => [r.id, r]));
  for (const r of regulators) {
    let card = byCountry.get(r.country_name);
    if (!card) {
      card = { country: r.country_name, code: r.country_code ?? null, regulators: [], pages: [], sources: [] };
      byCountry.set(r.country_name, card);
    }
    card.regulators.push(r);
  }
  for (const s of sources) {
    const r = regById.get(s.regulator_id);
    if (r) byCountry.get(r.country_name)?.sources.push(s);
  }
  for (const p of pages) {
    const r = regById.get(p.regulator_id);
    if (r) byCountry.get(r.country_name)?.pages.push(p);
  }
  const cards = [...byCountry.values()];
  for (const c of cards) {
    c.regulators.sort((a, b) => a.name.localeCompare(b.name));
    const regOrder = new Map(c.regulators.map((r, i) => [r.id, i]));
    c.pages.sort((a, b) => (regOrder.get(a.regulator_id) ?? 0) - (regOrder.get(b.regulator_id) ?? 0) || a.sort - b.sort);
    c.sources.sort((a, b) => a.id.localeCompare(b.id));
  }
  const byName = (a: CountryCard<S>, b: CountryCard<S>) => a.country.localeCompare(b.country);
  return {
    hers: cards.filter((c) => c.pages.length > 0).sort(byName),
    others: cards.filter((c) => c.pages.length === 0 && c.sources.length > 0).sort(byName),
  };
}

/** The person's last look at a country: the latest over its authorities. */
export function lastLook(card: Pick<CountryCard, 'regulators'>, looks: Map<string, string>): string | null {
  let best: string | null = null;
  for (const r of card.regulators) {
    const at = looks.get(r.id);
    if (at && (!best || Date.parse(at) > Date.parse(best))) best = at;
  }
  return best;
}

/** Where "New since you last looked" starts: the last look, or this week's Sunday when there is none, never
 *  more than MAX_LOOKBACK_DAYS back. */
export function sinceFor(look: string | null, weekStart: Date, now: Date): Date {
  const from = look ? new Date(look) : weekStart;
  const floor = new Date(now.getTime() - MAX_LOOKBACK_DAYS * 86_400_000);
  return from < floor ? floor : from;
}

/** The items of these authorities first seen at or after `since`, newest first. */
export function newSince(items: NewItem[], regulatorIds: string[], since: Date): NewItem[] {
  const ids = new Set(regulatorIds);
  const t = since.getTime();
  return items
    .filter((i) => ids.has(i.regulator_id) && Date.parse(i.first_seen_at) >= t)
    .sort((a, b) => Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at) || a.document_id.localeCompare(b.document_id));
}

/** How many items are new since the person last looked, across every country (the tab's "N new"). */
export function totalNew(
  regulators: CardRegulator[],
  items: NewItem[],
  looks: Map<string, string>,
  weekStart: Date,
  now: Date,
): number {
  const byCountry = new Map<string, CardRegulator[]>();
  for (const r of regulators) byCountry.set(r.country_name, [...(byCountry.get(r.country_name) ?? []), r]);
  let n = 0;
  for (const regs of byCountry.values()) {
    const since = sinceFor(lastLook({ regulators: regs }, looks), weekStart, now);
    n += newSince(
      items,
      regs.map((r) => r.id),
      since,
    ).length;
  }
  return n;
}

export type ReadState = 'read' | 'partial' | 'unread';

export interface PageStatus {
  state: ReadState;
  /** What the card says about the page. */
  label: string;
  /** Her page reaches the app as an e-mail subscription. */
  byEmail: boolean;
  /** The page's note, without a leading "By e-mail subscription" the label already says. */
  note: string | null;
}

const BY_EMAIL = /^By e-mail subscription[:.]?\s*/;

/** Whether the app reads one of her pages: only through sources that exist and are switched on. */
export function pageStatus(page: RegulatorPage, sources: Map<string, Pick<CardSource, 'enabled' | 'channel'>>): PageStatus {
  const live = page.read_by.map((id) => sources.get(id)).filter((s): s is Pick<CardSource, 'enabled' | 'channel'> => Boolean(s?.enabled));
  const byEmail = live.some((s) => s.channel === 'email');
  const state: ReadState = live.length === 0 ? 'unread' : page.partial ? 'partial' : 'read';
  let label =
    state === 'unread' ? 'Not read by the app — open it yourself' : state === 'partial' ? 'Partly read by the app' : 'Read by the app';
  if (byEmail) label += ', by e-mail subscription';
  const note = (byEmail ? (page.note ?? '').replace(BY_EMAIL, '') : page.note ?? '').trim();
  return { state, label, byEmail, note: note || null };
}

/** The page a person opens for a source: its page, else its own address when that is not a feed, else the
 *  authority's home page. Never a feed. */
export function sourcePage(s: Pick<CardSource, 'url' | 'page_url'>, homepage: string | null | undefined): string | null {
  if (s.page_url && !isFeedUrl(s.page_url)) return s.page_url;
  if (!isFeedUrl(s.url)) return s.url;
  return homepage && !isFeedUrl(homepage) ? homepage : null;
}

/** A source in plain words: the name of her page it reads, else what it reads and where. */
export function sourceLabel(s: CardSource, pages: RegulatorPage[]): string {
  const page = pages.find((p) => p.read_by.includes(s.id));
  if (page) return page.label;
  const where = hostOf(sourcePage(s, null) ?? '');
  const what = s.channel === 'email' ? `${KIND_LABEL[s.kind]} by e-mail` : KIND_LABEL[s.kind];
  return where ? `${what} · ${where}` : what;
}

/** One card's labels. Two sources that would read the same ("Safety notices · tga.gov.au" twice, the
 *  TGA alerts and updates pages) are told apart by the last part of the address they read. */
export function sourceLabels(sources: CardSource[], pages: RegulatorPage[]): Map<string, string> {
  const base = new Map(sources.map((s) => [s.id, sourceLabel(s, pages)]));
  const seen = new Map<string, number>();
  for (const l of base.values()) seen.set(l, (seen.get(l) ?? 0) + 1);
  return new Map(
    sources.map((s) => {
      const l = base.get(s.id)!;
      const tail = (seen.get(l) ?? 0) > 1 ? lastPathPart(sourcePage(s, null) ?? s.url) : '';
      return [s.id, tail ? `${l} · ${tail}` : l];
    }),
  );
}

function lastPathPart(url: string): string {
  try {
    const part = new URL(url).pathname.split('/').filter(Boolean).pop() ?? '';
    return decodeURIComponent(part).replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ').trim();
  } catch {
    return '';
  }
}

/** A mail source that has never received a notice is waiting, not working: the day it began waiting (the day
 *  it was added), else null. TGA's and Fimea's mail sources read "Working" for days with nothing in them
 *  (6 Nov 2026). The collector turns a source still waiting after its expected gap to "check it". */
export function waitingForMail(s: {
  enabled: boolean;
  channel: string;
  health: string;
  last_item_at: string | null;
  created_at: string | null;
}): string | null {
  if (!s.enabled || s.channel !== 'email' || s.last_item_at) return null;
  if (s.health === 'down' || s.health === 'blocked' || s.health === 'degraded') return null;
  return s.created_at;
}

/** Why a source is not read, shown beside its switch: the reason a source was switched off (or why the site
 *  refuses it) was kept only in the catalogue, so on 5 Nov 2026 the two TGA web pages were switched back on
 *  with no reason in sight and failed every run while TGA's e-mails were already read. */
export function offReason(s: { enabled: boolean; health: string; notes: string | null }): string | null {
  const note = s.notes?.trim();
  if (!note) return null;
  return !s.enabled || s.health === 'blocked' ? note : null;
}

/** Label watch and literature have screens of their own: their figures are not item lists here. */
export function listsItems(kind: SourceKind): boolean {
  return kind !== 'spc' && kind !== 'literature';
}

/**
 * The arguments of mark_country_looked (0056). The look is the time the list on screen was read, not the time
 * of the click: a notice that arrived while the card stayed open was never shown and stays new.
 */
export function markLookedArgs(regulatorId: string, readAt: string): { p_regulator: string; p_seen_to: string } {
  return { p_regulator: regulatorId, p_seen_to: readAt };
}
