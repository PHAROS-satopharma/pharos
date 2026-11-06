import { describe, expect, it } from 'vitest';
import { answerOf, answerText, countryAnswers, readsText, summaryLine, toCheckByHand, type Answer } from './answers';
import type { RegulatorPage } from '../sources/horizontal';
import type { Mention, ScreenRegulator, ScreenSource } from './types';

const source = (id: string, regulator_id: string, extra: Partial<ScreenSource> = {}): ScreenSource => ({
  id,
  regulator_id,
  kind: 'safety',
  channel: 'html',
  url: `https://example.test/${id}`,
  page_url: null,
  enabled: true,
  health: 'ok',
  notes: null,
  ...extra,
});

const page = (regulator_id: string, read_by: string[]): RegulatorPage => ({
  id: `${regulator_id}-page`,
  regulator_id,
  kind: 'safety',
  sort: 1,
  label: `${regulator_id} safety page`,
  url: `https://example.test/${regulator_id}`,
  read_by,
  partial: false,
  note: null,
});

const mention = (document_id: string, regulator_id: string, date: string, first_seen_at: string): Mention => ({
  document_id,
  source_id: `${regulator_id.toLowerCase()}-src`,
  regulator_id,
  regulator_name: regulator_id,
  country_name: '',
  country_code: '',
  title: `Notice ${document_id}`,
  lang: 'en',
  link: `https://example.test/${document_id}`,
  email_id: null,
  email_r2_key: null,
  date,
  published_date: date,
  first_seen_at,
  doc_type: 'dhpc',
  terms: [{ text: 'lornoxicam', lang: 'en' }],
  by_class: false,
  is_backfill: false,
  sections: null,
  issue_id: null,
  issue_status: null,
  decision: null,
});

const reg = (
  id: string,
  country_name: string,
  country_code: string,
  extra: Partial<ScreenRegulator> = {},
): ScreenRegulator => {
  const src = source(`${id.toLowerCase()}-src`, id);
  return {
    id,
    name: `${id} Agency`,
    country_name,
    country_code,
    homepage: null,
    hers: true,
    runs: 7,
    ok: 7,
    failed: 0,
    unread_page: false,
    pages: [page(id, [src.id])],
    sources: [src],
    mentions: [],
    ...extra,
  };
};

const REGS: ScreenRegulator[] = [
  // Germany: two authorities, one mention each; the newer one first
  reg('BFARM', 'Germany', 'DE', { mentions: [mention('d1', 'BFARM', '2026-11-03', '2026-11-03T08:00:00Z')] }),
  reg('PEI', 'Germany', 'DE', { mentions: [mention('d2', 'PEI', '2026-11-05', '2026-11-05T08:00:00Z')] }),
  reg('MHRA', 'United Kingdom', 'GB'),
  reg('EDA', 'Egypt', 'EG', { runs: 0, ok: 0 }),
  reg('JFDA', 'Jordan', 'JO', { runs: 4, ok: 3, failed: 1 }),
  reg('TGA', 'Australia', 'AU', { unread_page: true }),
  reg('HSA', 'Singapore', 'SG'),
  // not on her list: no pages
  reg('FDA', 'United States', 'US', { hers: false, pages: [], runs: 2, ok: 2 }),
  reg('HC', 'Canada', 'CA', { hers: false, pages: [], runs: 0, ok: 0 }),
];

describe('answerOf', () => {
  it('puts a mention before anything the app could not read', () => {
    expect(answerOf({ mentions: [1], runs: 0, failed: 0, unreadPage: true })).toBe('mentioned');
    expect(answerOf({ mentions: [], runs: 0, failed: 0, unreadPage: true })).toBe('not_read');
    expect(answerOf({ mentions: [], runs: 3, failed: 1, unreadPage: true })).toBe('failed');
    expect(answerOf({ mentions: [], runs: 3, failed: 0, unreadPage: true })).toBe('unread_page');
    expect(answerOf({ mentions: [], runs: 3, failed: 0, unreadPage: false })).toBe('fine');
  });

  it('counts only an unread country, a failed read or an unread page as to check by hand', () => {
    const all: Answer[] = ['mentioned', 'not_read', 'failed', 'unread_page', 'fine'];
    expect(all.map(toCheckByHand)).toEqual([
      false,
      true,
      true,
      true,
      false,
    ]);
  });
});

describe('countryAnswers', () => {
  const { hers, others } = countryAnswers(REGS);

  it('groups authorities by country and puts her countries apart from the others', () => {
    expect(hers.map((c) => c.country)).toEqual([
      'Germany',
      'Egypt',
      'Jordan',
      'Australia',
      'Singapore',
      'United Kingdom',
    ]);
    expect(others.map((c) => c.country)).toEqual(['Canada', 'United States']);
    expect(hers[0].regulators.map((r) => r.id)).toEqual(['BFARM', 'PEI']);
  });

  it('gives each country its answer, its mentions newest first, and its reads', () => {
    expect(hers.map((c) => c.answer)).toEqual(['mentioned', 'not_read', 'failed', 'unread_page', 'fine', 'fine']);
    expect(others.map((c) => c.answer)).toEqual(['not_read', 'fine']);
    expect(hers[0].mentions.map((m) => m.document_id)).toEqual(['d2', 'd1']);
    expect(hers[0].runs).toBe(14);
    expect(hers[2].failed).toBe(1);
  });

  it('says each answer in plain words', () => {
    expect(hers.map(answerText)).toEqual([
      'Mentioned in 2 notices',
      'Not read in these days — check it by hand',
      '1 of 4 reads failed — check it by hand',
      'A page of hers is not read by the app — check it by hand',
      'Nothing found',
      'Nothing found',
    ]);
    expect(readsText(hers[2])).toBe('Read 4 times in these days, 1 failed');
    expect(readsText(hers[1])).toBe('Not read in these days');
    expect(readsText({ runs: 1, failed: 0 })).toBe('Read 1 time in these days');
  });

  it('sums the screen up in one line', () => {
    expect(summaryLine([...hers, ...others])).toBe(
      'Mentioned in 1 of 8 countries · 3 nothing found · 4 to check by hand',
    );
    expect(summaryLine(hers.slice(0, 1))).toBe('Mentioned in 1 of 1 country · 0 nothing found · 0 to check by hand');
  });
});
