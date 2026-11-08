import { describe, expect, it } from 'vitest';
import type { RegulatorPage } from './horizontal';
import {
  authorityId,
  authorityRow,
  checkAuthority,
  checkPage,
  cleanUrl,
  nextSort,
  pageRow,
  readerWarning,
  sameAddress,
  type PageDraft,
} from './pageRules';

const page = (p: Partial<RegulatorPage>): RegulatorPage => ({
  id: 'p1',
  regulator_id: 'SFDA',
  kind: 'safety',
  sort: 1,
  label: 'Safety alerts',
  url: 'https://www.sfda.gov.sa/en/alerts',
  read_by: [],
  partial: false,
  note: null,
  ...p,
});
const draft = (d: Partial<PageDraft>): PageDraft => ({
  regulator_id: 'SFDA',
  kind: 'safety',
  label: 'Drug safety communications',
  url: 'https://www.sfda.gov.sa/en/communications',
  note: '',
  ...d,
});

describe('a link she adds or changes', () => {
  it('is saved when it has a name and a full web address', () => {
    expect(checkPage(draft({}), [page({})])).toBeNull();
  });
  it('needs an authority, a name and an http(s) address', () => {
    expect(checkPage(draft({ regulator_id: '' }), [])).toMatch(/authority/);
    expect(checkPage(draft({ label: '   ' }), [])).toMatch(/name/);
    expect(checkPage(draft({ url: 'www.sfda.gov.sa' }), [])).toMatch(/web address/);
    expect(checkPage(draft({ url: 'ftp://sfda.gov.sa/x' }), [])).toMatch(/web address/);
    expect(checkPage(draft({ url: 'javascript:alert(1)' }), [])).toMatch(/web address/);
    expect(checkPage(draft({ label: 'x'.repeat(201) }), [])).toMatch(/200/);
  });
  it('is refused when the authority already has the same address, whatever the slash or the host case', () => {
    const pages = [page({ id: 'a', url: 'https://www.sfda.gov.sa/en/alerts' })];
    expect(checkPage(draft({ url: 'https://WWW.sfda.gov.sa/en/alerts/' }), pages)).toMatch(/Safety alerts/);
    expect(checkPage(draft({ regulator_id: 'EDE', url: 'https://www.sfda.gov.sa/en/alerts' }), pages)).toBeNull();
  });
  it('keeps its own address when it is changed', () => {
    const p = page({ id: 'a' });
    expect(checkPage(draft({ url: p.url, label: 'Renamed' }), [p], 'a')).toBeNull();
  });
  it('never writes read_by or partial, and an empty note is no note', () => {
    const row = pageRow(draft({ label: '  Alerts  ', note: '  ' }));
    expect(row).toEqual({
      regulator_id: 'SFDA',
      kind: 'safety',
      label: 'Alerts',
      url: 'https://www.sfda.gov.sa/en/communications',
      note: null,
    });
    expect(row).not.toHaveProperty('read_by');
    expect(row).not.toHaveProperty('partial');
  });
  it('goes last in its authority’s list', () => {
    const pages = [page({ sort: 3 }), page({ id: 'b', sort: 7, regulator_id: 'EDE' })];
    expect(nextSort(pages, 'SFDA')).toBe(4);
    expect(nextSort(pages, 'NEW')).toBe(1);
  });
});

describe('addresses', () => {
  it('reads only full http and https addresses', () => {
    expect(cleanUrl(' https://eda.mohp.gov.eg/ ')).toBe('https://eda.mohp.gov.eg/');
    expect(cleanUrl('https://localhost/x')).toBeNull();
    expect(cleanUrl('')).toBeNull();
  });
  it('treats a #part as the same page and a different path as another', () => {
    expect(sameAddress('https://a.org/x#top', 'https://a.org/x')).toBe(true);
    expect(sameAddress('https://a.org/x', 'https://a.org/y')).toBe(false);
  });
});

describe('changing the address of a page the app reads', () => {
  it('warns that the app’s reader is not moved', () => {
    const read = page({ read_by: ['sfda-sa'] });
    expect(readerWarning(read, 'https://www.sfda.gov.sa/en/new')).toMatch(/reader/);
    expect(readerWarning(read, read.url)).toBeNull();
    expect(readerWarning(page({}), 'https://www.sfda.gov.sa/en/new')).toBeNull();
  });
});

describe('a new local reference', () => {
  const a = { country_name: 'Egypt', country_code: 'eg', name: 'Egyptian Drug Authority', short: 'EDA' };
  it('becomes a regulator row with a catalogue-style id', () => {
    expect(checkAuthority(a, new Set())).toBeNull();
    expect(authorityRow(a)).toEqual({
      id: 'EDA',
      country_code: 'EG',
      country_name: 'Egypt',
      name: 'Egyptian Drug Authority',
      languages: ['en'],
    });
  });
  it('is refused when its id is taken, the code is not two letters, or a field is empty', () => {
    expect(checkAuthority(a, new Set(['EDA']))).toMatch(/already in PHAROS/);
    expect(checkAuthority({ ...a, country_code: 'EGY' }, new Set())).toMatch(/two letters/);
    expect(checkAuthority({ ...a, name: '' }, new Set())).toMatch(/name/);
    expect(checkAuthority({ ...a, country_name: ' ' }, new Set())).toMatch(/country/);
    expect(checkAuthority({ ...a, short: 'هيئة', name: 'هيئة الدواء' }, new Set())).toMatch(/Latin/);
  });
  it('makes the id from the short name, else the name', () => {
    expect(authorityId('Jordan FDA')).toBe('JORDAN_FDA');
    expect(authorityId('  Médicaments ')).toBe('MEDICAMENTS');
  });
});
