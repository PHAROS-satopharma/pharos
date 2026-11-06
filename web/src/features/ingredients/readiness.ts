// How far an ingredient is prepared, in her words (ingredient_readiness(), migration 0045). Pure: the component
// (Readiness.tsx) reads the database; collectors/report_weekly.py (readiness_items, readiness_text) says the
// same, and tests/test_report_weekly.py holds both to these phrases.
import { formatDate } from '../../lib/format';

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
  ncbi: { searches: number; expected: number; look_back_done: boolean; last_run: string | null };
  label_watch: {
    products: number;
    by_source: Record<string, ReadinessSource>;
    waiting: string[];
    empty: string[];
    first_snapshot: boolean;
    japan_code: boolean;
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

/** What is still running or still to come, in the order the days bring it. Empty when nothing is. */
export function readinessItems(r: Readiness): string[] {
  const items: string[] = [];
  if (r.names.languages_with_a_name === 0) items.push('no name to look for yet');
  if (r.class.atc && r.class.classes === 0) items.push('class words waiting');
  if (!r.past_check.done) items.push(r.past_check.job_running ? 'check of the past running' : 'check of the past waiting');
  if (!r.ncbi.look_back_done) items.push(r.ncbi.searches > 0 ? 'NCBI look-back running' : 'NCBI look-back waiting');
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

/** The facts under the line: labels, Japan, the EURD list, EMA's literature monitoring, Telegram. */
export function readinessNotes(r: Readiness): string[] {
  const notes: string[] = [];
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

/** A PMDA code: the 7-character product code, or the 12-character YJ code that starts with it. */
export function isJapanCode(s: string): boolean {
  return /^[0-9]{4}[0-9A-Z]{3}(?:[0-9A-Z]{5})?$/.test(s.trim());
}
