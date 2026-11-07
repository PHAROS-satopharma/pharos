import { describe, expect, it } from 'vitest';
import {
  countryList,
  isJapanCode,
  readinessItems,
  readinessLine,
  readinessNotes,
  type Readiness,
} from './readiness';

/** A freshly saved ingredient: one name, its class made at the next run, nothing run yet (ingredient_readiness, 0045). */
const fresh: Readiness = {
  names: { languages_with_a_name: 1, of: 15, missing: ['de', 'fr'] },
  class: { atc: true, classes: 0, words: 0, confirmed: false },
  past_check: { done: false, words_due: 1, job_running: false },
  ncbi: { searches: 0, expected: 2, look_back_done: false, last_run: null },
  label_watch: {
    products: 0,
    by_source: {
      'spc-cima': { country: 'Spain', regulator: 'AEMPS', products: 0, read: false },
      'spc-pmda': { country: 'Japan', regulator: 'PMDA', products: 0, read: false },
    },
    waiting: ['Japan', 'Spain'],
    empty: [],
    first_snapshot: false,
    japan_code: false,
  },
  eurd: { found: false, list_read: true, frequency: null, dlp: null, next_submission: null },
  ema_mlm: { monitored: false },
  telegram: { people: [] },
  ready: false,
};

const ready: Readiness = {
  names: { languages_with_a_name: 12, of: 15, missing: ['ja', 'ko', 'ar'] },
  class: { atc: true, classes: 1, words: 17, confirmed: true },
  past_check: { done: true, words_due: 0, job_running: false },
  ncbi: { searches: 4, expected: 4, look_back_done: true, last_run: '2026-11-06T00:40:00Z' },
  label_watch: {
    products: 3,
    by_source: {
      'spc-cima': { country: 'Spain', regulator: 'AEMPS', products: 2, read: true },
      'spc-pmda': { country: 'Japan', regulator: 'PMDA', products: 1, read: true },
      'spc-mhra': { country: 'United Kingdom', regulator: 'MHRA', products: 0, read: true },
    },
    waiting: [],
    empty: ['United Kingdom'],
    first_snapshot: true,
    japan_code: true,
  },
  eurd: { found: true, list_read: true, frequency: '7 years', dlp: '2031-12-01', next_submission: '2032-02-29' },
  ema_mlm: { monitored: true },
  telegram: { people: ['Sama Mosaad'] },
  ready: true,
};

describe('readiness on the ingredient row', () => {
  it('lists what is still running or still to come, in her words, never codes', () => {
    expect(readinessItems(fresh)).toEqual([
      'class words waiting',
      'check of the past waiting',
      'PubMed look-back waiting',
      'label watch on Monday (Japan, Spain)',
      'nobody receives its Telegram messages yet',
    ]);
    expect(readinessLine(fresh)).toBe(
      'Still preparing: class words waiting · check of the past waiting · PubMed look-back waiting · ' +
        'label watch on Monday (Japan, Spain) · nobody receives its Telegram messages yet',
    );
  });

  it('says "running" once the check of the past or the PubMed look-back has started', () => {
    const running: Readiness = {
      ...fresh,
      class: { atc: true, classes: 1, words: 17, confirmed: false },
      past_check: { done: false, words_due: 18, job_running: true },
      ncbi: { searches: 2, expected: 4, look_back_done: false, last_run: '2026-11-06T00:40:00Z' },
      telegram: { people: ['Sama Mosaad'] },
    };
    expect(readinessItems(running)).toEqual([
      'check of the past running',
      'PubMed look-back running',
      'label watch on Monday (Japan, Spain)',
    ]);
  });

  it('waits for the Europe PMC look-back only while its watch is on and it holds Ready', () => {
    const epmc = { watched: true, searches: 0, expected: 2, look_back_done: false, last_run: null };
    expect(readinessItems({ ...ready, europepmc: epmc })).toEqual(['Europe PMC look-back waiting']);
    expect(readinessItems({ ...ready, europepmc: { ...epmc, searches: 1 } })).toEqual([
      'Europe PMC look-back running',
    ]);
    expect(readinessItems({ ...ready, europepmc: { ...epmc, watched: false } })).toEqual([]);
    expect(readinessItems({ ...ready, europepmc: { ...epmc, searches: 2, look_back_done: true } })).toEqual([]);
    // 0092: it fills in the background and holds nothing
    expect(readinessItems({ ...ready, europepmc: { ...epmc, holds_ready: false } })).toEqual([]);
  });

  it('is Ready when everything that follows by itself has run', () => {
    expect(readinessItems(ready)).toEqual([]);
    expect(readinessLine(ready)).toBe('Ready');
  });

  it('needs no class words without an ATC code, and no name is a problem of its own', () => {
    const noAtc: Readiness = { ...ready, class: { atc: false, classes: 0, words: 0, confirmed: false } };
    expect(readinessItems(noAtc)).toEqual([]);
    const noName: Readiness = { ...ready, names: { languages_with_a_name: 0, of: 15, missing: ['en'] } };
    expect(readinessItems(noName)).toEqual(['no name to look for yet']);
  });

  it('treats a label watch that ran and found nothing as an answer, not as still running', () => {
    const none: Readiness = {
      ...ready,
      label_watch: { ...ready.label_watch, products: 0, waiting: [], empty: ['Japan', 'Spain', 'United Kingdom'] },
    };
    expect(readinessItems(none)).toEqual([]);
    expect(readinessNotes(none)).toContain('No label found in any watched country');
  });

  it('adds the facts she needs under the line: labels, Japan, EURD, EMA, Telegram', () => {
    expect(readinessNotes(ready)).toEqual([
      'No name in Arabic, Japanese and Korean; notices in those languages are matched by its other names only',
      '3 label products in Japan, Spain',
      'PSUR every 7 years, data lock point 1 Dec 2031, submission 29 Feb 2032',
      'Literature monitored by EMA',
      'Telegram: Sama Mosaad',
    ]);
    expect(readinessNotes(fresh)).toEqual([
      'No name in French and German; notices in those languages are matched by its other names only',
      'No Japan code yet, so Japan’s label watch cannot find its package inserts',
      'Not on the EURD list',
      'Literature not monitored by EMA',
    ]);
    expect(readinessNotes({ ...fresh, eurd: { ...fresh.eurd, list_read: false } })).toContain('EURD list not read yet');
  });

  it('names the languages it has no name in, which never clear by themselves', () => {
    const one: Readiness = { ...ready, names: { languages_with_a_name: 14, of: 15, missing: ['da'] } };
    expect(readinessNotes(one)[0]).toBe('No name in Danish; notices in Danish are matched by its other names only');
    expect(readinessItems(one)).toEqual([]);
    expect(readinessLine(one)).toBe('Ready');
    const four: Readiness = { ...ready, names: { languages_with_a_name: 11, of: 15, missing: ['da', 'is', 'nb', 'sv'] } };
    expect(readinessNotes(four)[0]).toBe(
      'No name in Danish, Icelandic, Norwegian Bokmål and Swedish; notices in those languages are matched by its other names only',
    );
    const many: Readiness = {
      ...ready,
      names: { languages_with_a_name: 6, of: 15, missing: ['da', 'fi', 'is', 'it', 'ja', 'ko', 'nb', 'nl', 'sv'] },
    };
    expect(readinessNotes(many)[0]).toBe(
      'No name in 9 of 15 languages; notices in those languages are matched by its other names only',
    );
    const all: Readiness = { ...ready, names: { languages_with_a_name: 15, of: 15, missing: [] } };
    expect(readinessNotes(all).some((n) => n.startsWith('No name in'))).toBe(false);
    const none: Readiness = { ...ready, names: { languages_with_a_name: 0, of: 15, missing: ['en'] } };
    expect(readinessNotes(none).some((n) => n.startsWith('No name in'))).toBe(false);
  });

  it('names up to three countries, then counts them', () => {
    expect(countryList(['Spain'])).toBe('Spain');
    expect(countryList(['Japan', 'Spain', 'United Kingdom'])).toBe('Japan, Spain, United Kingdom');
    expect(countryList(['France', 'Germany', 'Japan', 'Spain'])).toBe('4 countries');
    expect(countryList([])).toBe('');
  });

  it('knows a Japan code: 7 characters, or the 12-character YJ code that starts with it', () => {
    expect(isJapanCode('1149036')).toBe(true);
    expect(isJapanCode('2190417')).toBe(true);
    expect(isJapanCode('1149036F1025')).toBe(true);
    expect(isJapanCode(' 1149036 ')).toBe(true);
    expect(isJapanCode('M01AC05')).toBe(false);
    expect(isJapanCode('114903')).toBe(false);
    expect(isJapanCode('')).toBe(false);
  });
});
