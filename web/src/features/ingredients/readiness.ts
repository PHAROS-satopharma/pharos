// How far an ingredient is prepared, in her words (ingredient_readiness(), migrations 0045 and 0082). Pure: the
// component (Readiness.tsx) reads the database; collectors/report_weekly.py (readiness_items, readiness_text) says
// the same, and tests/test_report_weekly.py holds both to these phrases.
import { formatDate } from '../../lib/format';
import { languageName } from '../../lib/labels';

export interface ReadinessSource {
  country: string;
  regulator: string;
  products: number;
  read: boolean;
}

export interface Readiness {
  names: { languages_with_a_name: number; of: number; missing: string[] };
  class: { atc: boolean; classes: number; words: number; confirmed: boolean };
  past_check: { done: boolean; words_due: number; job_running: boolean };
  /** The ingredient's own name in PubMed (titles and abstracts) and its 12-month look-back: since 0092 the only
   *  literature search Ready waits for. */
  ncbi: { searches: number; expected: number; look_back_done: boolean; last_run: string | null };
  /** The Europe PMC watch (0082): the same words, once each. Since 0092 it fills in the background and
   *  holds_ready is false; absent before 0082 is applied. */
  europepmc?: {
    watched: boolean;
    holds_ready?: boolean;
    searches: number;
    expected: number;
    look_back_done: boolean;
    last_run: string | null;
  };
  label_watch: {
    products: number;
    by_source: Record<string, ReadinessSource>;
    waiting: string[];
    empty: string[];
    first_snapshot: boolean;
    japan_code: boolean;
    /** Her database pages for this ingredient (0095); absent before 0095 is applied. A page is read when its source
     *  has read every one of the ingredient's labels at least once; `reading`, `labels_unread` and `reading_pages`
     *  are 0113's and absent before it is applied. */
    pages?: {
      total: number;
      read: number;
      reading?: number;
      labels_unread?: number;
      waiting: number;
      not_read: number;
      reading_pages?: string[];
      waiting_pages: string[];
    };
  };
  eurd: {
    found: boolean;
    list_read: boolean;
    frequency: string | null;
    dlp: string | null;
    next_submission: string | null;
  };
  ema_mlm: { monitored: boolean };
  telegram: { people: string[] };
  ready: boolean;
}

/** Up to three country names; more are counted. */
export function countryList(countries: string[]): string {
  if (countries.length === 0) return '';
  return countries.length <= 3 ? countries.join(', ') : `${countries.length} countries`;
}

/** "Danish", "Danish and Swedish", "Danish, Icelandic and Swedish"; more than five are counted ("9 of 15 languages"). */
export function languageList(codes: string[], of: number): string {
  if (codes.length > 5) return `${codes.length} of ${of} languages`;
  const names = codes.map((c) => languageName(c)).sort((a, b) => a.localeCompare(b));
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

/** The languages the authorities write in where it has no name of its own. Never "still preparing": nothing adds
 *  a name by itself, and a language may need none (Danish writes "carvedilol"). Its other names are still looked
 *  for in every language, so the note says what is matched there. Nothing when it has no name at all: the line
 *  already says "no name to look for yet". */
export function missingNamesNote(r: Readiness): string | null {
  const missing = r.names.missing ?? [];
  if (r.names.languages_with_a_name === 0 || missing.length === 0) return null;
  const where = missing.length === 1 ? `notices in ${languageName(missing[0])}` : 'notices in those languages';
  return `No name in ${languageList(missing, r.names.of)}; ${where} are matched by its other names only`;
}

/** What is still running or still to come, in the order the days bring it. Empty when nothing is. */
export function readinessItems(r: Readiness): string[] {
  const items: string[] = [];
  if (r.names.languages_with_a_name === 0) items.push('no name to look for yet');
  if (r.class.atc && r.class.classes === 0) items.push('class words waiting');
  if (!r.past_check.done) items.push(r.past_check.job_running ? 'check of the past running' : 'check of the past waiting');
  if (!r.ncbi.look_back_done) items.push(r.ncbi.searches > 0 ? 'PubMed look-back running' : 'PubMed look-back waiting');
  const epmc = r.europepmc;
  if (epmc?.watched && epmc.holds_ready !== false && !epmc.look_back_done) {
    items.push(epmc.searches > 0 ? 'Europe PMC look-back running' : 'Europe PMC look-back waiting');
  }
  if (r.label_watch.products === 0 && r.label_watch.waiting.length > 0) {
    items.push(`label watch on Monday (${countryList(r.label_watch.waiting)})`);
  }
  if (r.telegram.people.length === 0) items.push('nobody receives its Telegram messages yet');
  return items;
}

/** The one line on the row: "Ready", or "Still preparing: …". */
export function readinessLine(r: Readiness): string {
  const items = readinessItems(r);
  return items.length === 0 && r.ready ? 'Ready' : `Still preparing: ${items.join(' · ')}`;
}

/** The facts under the line: languages without a name, labels, Japan, the EURD list, EMA's literature monitoring,
 *  Telegram. */
export function readinessNotes(r: Readiness): string[] {
  const notes: string[] = [];
  const names = missingNamesNote(r);
  if (names) notes.push(names);
  const lw = r.label_watch;
  if (lw.products > 0) {
    const where = Object.values(lw.by_source)
      .filter((s) => s.products > 0)
      .map((s) => s.country);
    const countries = [...new Set(where)].sort((a, b) => a.localeCompare(b));
    notes.push(`${lw.products} label ${lw.products === 1 ? 'product' : 'products'} in ${countries.join(', ')}`);
  } else if (lw.waiting.length === 0 && lw.empty.length > 0) {
    notes.push('No label found in any watched country');
  }
  const pages = labelPagesNote(lw.pages);
  if (pages) notes.push(pages);
  if (!lw.japan_code) notes.push('No Japan code yet, so Japan’s label watch cannot find its package inserts');
  if (r.eurd.found) {
    notes.push(
      `PSUR every ${r.eurd.frequency ?? '—'}, data lock point ${formatDate(r.eurd.dlp)}, ` +
        `submission ${formatDate(r.eurd.next_submission)}`,
    );
  } else {
    notes.push(r.eurd.list_read ? 'Not on the EURD list' : 'EURD list not read yet');
  }
  notes.push(r.ema_mlm.monitored ? 'Literature monitored by EMA' : 'Literature not monitored by EMA');
  if (r.telegram.people.length > 0) notes.push(`Telegram: ${r.telegram.people.join(', ')}`);
  return notes;
}

/** "Label databases: 7 of 27 pages read · 11 being read (2,257 labels not read yet) · 9 not read (reasons on the
 *  Sources page)". A page is read only when its labels were (0113): until 13 Nov 2026 a page counted as read when
 *  its source had run, so DailyMed showed read after a run that read none of its 1,911 labels. */
export function labelPagesNote(pages: Readiness['label_watch']['pages']): string | null {
  if (!pages || pages.total === 0) return null;
  const parts = [`${pages.read} of ${pages.total} ${pages.total === 1 ? 'page' : 'pages'} read`];
  if (pages.reading) {
    const left = pages.labels_unread ?? 0;
    const unread = left > 0 ? ` (${left.toLocaleString('en-GB')} ${left === 1 ? 'label' : 'labels'} not read yet)` : '';
    parts.push(`${pages.reading} being read${unread}`);
  }
  if (pages.waiting > 0) parts.push(`${pages.waiting} waiting for the weekly run`);
  if (pages.not_read > 0) parts.push(`${pages.not_read} not read (reasons on the Sources page)`);
  return `Label databases: ${parts.join(' · ')}`;
}

/** A PMDA code: the 7-character product code, or the 12-character YJ code that starts with it. */
export function isJapanCode(s: string): boolean {
  return /^[0-9]{4}[0-9A-Z]{3}(?:[0-9A-Z]{5})?$/.test(s.trim());
}
