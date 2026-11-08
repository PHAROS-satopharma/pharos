import { describe, expect, it } from 'vitest';
import {
  checkRef,
  nextRefSort,
  refFound,
  refRow,
  refStatus,
  weekDays,
  type LiteratureRef,
  type RefWeek,
} from './literatureRefs';

const when = (iso: string) => `[${iso}]`;
const week = (extra: Partial<RefWeek> = {}): RefWeek => ({
  id: 'r1',
  scope: 'global',
  name: 'PubMed (NCBI)',
  url: 'https://pubmed.ncbi.nlm.nih.gov/',
  note: null,
  by_hand: false,
  searched_in: ['pubmed'],
  journal_like: null,
  searches: 0,
  last_searched: null,
  hits: 0,
  found: null,
  check: null,
  ...extra,
});
const ref = (id: string, scope: 'global' | 'local', name: string, url: string, sort = 10): LiteratureRef => ({
  id,
  scope,
  name,
  url,
  searched_in: [],
  journal_like: null,
  note: null,
  sort,
  active: true,
});
const REFS = [
  ref('a', 'local', 'Al-Azhar Medical Journal', 'https://amj.journals.ekb.eg/', 10),
  ref('b', 'local', 'Ain Shams Medical Journal', 'https://asmj.journals.ekb.eg/', 20),
  ref('c', 'global', 'Medscape', 'https://www.medscape.com/', 50),
];

describe('weekDays', () => {
  it('gives Sunday to Saturday, Cairo days, for the week that starts at Cairo midnight', () => {
    // Sunday 1 Nov 2026, 00:00 in Cairo (UTC+2) is 31 Oct 22:00 UTC
    expect(weekDays(new Date('2026-10-31T22:00:00Z'))).toEqual({ from: '2026-11-01', to: '2026-11-07' });
  });
});

describe('refStatus', () => {
  it('counts the app’s searches of the week, with the last one', () => {
    expect(refStatus(week({ searches: 14, last_searched: 'T' }), when)).toEqual({
      text: 'Searched by the app — 14 searches this week, last [T]',
      tone: 'ok',
    });
    expect(refStatus(week({ searches: 1, last_searched: 'T' }), when).text).toBe(
      'Searched by the app — 1 search this week, last [T]',
    );
  });

  it('says so when the app has not searched yet this week', () => {
    expect(refStatus(week(), when)).toEqual({
      text: 'Searched by the app — no search recorded this week yet',
      tone: 'warning',
    });
  });

  it('names who checked by hand, when, and what was found', () => {
    const hand = { by_hand: true, searched_in: [] };
    expect(refStatus(week(hand), when)).toEqual({ text: 'Checked by hand — not checked this week', tone: 'danger' });
    expect(
      refStatus(week({ ...hand, check: { result: 'nothing', note: null, checked_at: 'T', checked_by: 'Dr Sama' } }), when),
    ).toEqual({ text: 'Checked by hand — Dr Sama, [T]: nothing found', tone: 'ok' });
    expect(
      refStatus(
        week({ ...hand, check: { result: 'found', note: 'One case report', checked_at: 'T', checked_by: 'Dr Sama' } }),
        when,
      ).text,
    ).toBe('Checked by hand — Dr Sama, [T]: found — One case report');
  });
});

describe('refFound', () => {
  it('writes the negative result in words', () => {
    expect(refFound(week({ found: 0 }))).toBe('Nothing found');
    expect(refFound(week({ found: 1 }))).toBe('1 paper');
    expect(refFound(week({ found: 3 }))).toBe('3 papers');
    expect(refFound(week({ by_hand: true }))).toBe('Not checked');
    expect(
      refFound(week({ by_hand: true, check: { result: 'nothing', note: null, checked_at: 'T', checked_by: 'X' } })),
    ).toBe('Nothing found');
  });
});

describe('checkRef', () => {
  const draft = { scope: 'local' as const, name: 'Egyptian Journal of Hospital Medicine', url: 'https://ejhm.journals.ekb.eg/', note: '' };

  it('accepts a new journal', () => {
    expect(checkRef(draft, REFS)).toBeNull();
  });

  it('wants a name and a full http(s) address', () => {
    expect(checkRef({ ...draft, name: '  ' }, REFS)).toMatch(/name/);
    expect(checkRef({ ...draft, url: 'ejhm.journals.ekb.eg' }, REFS)).toMatch(/https:\/\//);
    expect(checkRef({ ...draft, url: 'javascript:alert(1)' }, REFS)).toMatch(/https:\/\//);
  });

  it('refuses a name or an address already in the same list, not in the other one', () => {
    expect(checkRef({ ...draft, name: 'al-azhar medical journal' }, REFS)).toMatch(/already in the Local list/);
    expect(checkRef({ ...draft, url: 'https://AMJ.journals.ekb.eg' }, REFS)).toMatch(/as Al-Azhar Medical Journal/);
    expect(checkRef({ ...draft, scope: 'global', url: 'https://amj.journals.ekb.eg/' }, REFS)).toBeNull();
  });

  it('lets a reference keep its own name and address when changed', () => {
    expect(checkRef({ scope: 'local', name: 'Al-Azhar Medical Journal', url: 'https://amj.journals.ekb.eg/', note: 'x' }, REFS, 'a')).toBeNull();
  });
});

describe('refRow and nextRefSort', () => {
  it('trims what is saved, and puts a new one after the last of its list', () => {
    expect(refRow({ scope: 'local', name: ' A ', url: ' https://a.example.test/ ', note: ' ' })).toEqual({
      scope: 'local',
      name: 'A',
      url: 'https://a.example.test/',
      note: null,
    });
    expect(nextRefSort(REFS, 'local')).toBe(30);
    expect(nextRefSort([], 'global')).toBe(10);
  });
});
