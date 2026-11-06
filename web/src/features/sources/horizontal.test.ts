import { describe, expect, it } from 'vitest';
import {
  FEED_URL,
  MAX_LOOKBACK_DAYS,
  cairoWeekStart,
  countryCards,
  isFeedUrl,
  lastLook,
  markLookedArgs,
  newSince,
  pageStatus,
  sinceFor,
  offReason,
  sourceLabel,
  sourceLabels,
  sourcePage,
  totalNew,
  type CardRegulator,
  type CardSource,
  type NewItem,
  type RegulatorPage,
} from './horizontal';

describe('cairoWeekStart', () => {
  it('is Sunday 00:00 in Cairo, in winter time (UTC+2)', () => {
    // Friday 6 Nov 2026 → Sunday 1 Nov 2026, 00:00 Cairo
    expect(cairoWeekStart(new Date('2026-11-06T10:00:00Z')).toISOString()).toBe('2026-10-31T22:00:00.000Z');
  });

  it('is Sunday 00:00 in Cairo, in summer time (UTC+3)', () => {
    // Wednesday 15 Jul 2026 → Sunday 12 Jul 2026, 00:00 Cairo
    expect(cairoWeekStart(new Date('2026-07-15T12:00:00Z')).toISOString()).toBe('2026-07-11T21:00:00.000Z');
  });

  it('turns over at midnight in Cairo, not in UTC', () => {
    // Saturday 7 Nov, 23:59 Cairo is still the week of 1 Nov; a minute later a new week begins
    expect(cairoWeekStart(new Date('2026-11-07T21:59:00Z')).toISOString()).toBe('2026-10-31T22:00:00.000Z');
    expect(cairoWeekStart(new Date('2026-11-07T22:00:00Z')).toISOString()).toBe('2026-11-07T22:00:00.000Z');
  });
});

const reg = (id: string, name: string, country_name: string, country_code: string): CardRegulator => ({
  id,
  name,
  country_name,
  country_code,
  homepage: null,
});
const REGULATORS = [
  reg('PEI', 'Paul-Ehrlich-Institut', 'Germany', 'DE'),
  reg('BFARM', 'Bundesinstitut für Arzneimittel und Medizinprodukte', 'Germany', 'DE'),
  reg('MHRA', 'Medicines and Healthcare products Regulatory Agency', 'United Kingdom', 'GB'),
  reg('EMA', 'European Medicines Agency', 'European Union', 'EU'),
  reg('EDA', 'Egyptian Drug Authority', 'Egypt', 'EG'),
  reg('JFDA', 'Jordan Food and Drug Administration', 'Jordan', 'JO'),
];
const src = (id: string, regulator_id: string, extra: Partial<CardSource> = {}): CardSource => ({
  id,
  regulator_id,
  kind: 'safety',
  channel: 'html',
  url: `https://example.test/${id}`,
  page_url: null,
  enabled: true,
  ...extra,
});
const SOURCES = [src('pei-rhb', 'PEI'), src('bfarm-rhb', 'BFARM'), src('mhra-dsu', 'MHRA'), src('ema-dhpc', 'EMA'), src('eda-eg', 'EDA')];
const page = (regulator_id: string, sort: number, read_by: string[], extra: Partial<RegulatorPage> = {}): RegulatorPage => ({
  id: `${regulator_id}-${sort}`,
  regulator_id,
  kind: 'safety',
  sort,
  label: `${regulator_id} page ${sort}`,
  url: `https://example.test/${regulator_id}/${sort}`,
  read_by,
  partial: false,
  note: null,
  ...extra,
});
const PAGES = [page('MHRA', 2, ['mhra-dsu']), page('MHRA', 1, []), page('BFARM', 1, ['bfarm-rhb']), page('EMA', 1, ['ema-dhpc'])];

describe('countryCards', () => {
  const { hers, others } = countryCards(REGULATORS, PAGES, SOURCES);

  it('puts her countries first, A to Z, the European Union among them', () => {
    expect(hers.map((c) => c.country)).toEqual(['European Union', 'Germany', 'United Kingdom']);
  });

  it('keeps one card per country, with every authority and source of it', () => {
    const de = hers.find((c) => c.country === 'Germany');
    expect(de?.regulators.map((r) => r.id)).toEqual(['BFARM', 'PEI']);
    expect(de?.sources.map((s) => s.id)).toEqual(['bfarm-rhb', 'pei-rhb']);
    expect(de?.code).toBe('DE');
  });

  it('keeps her pages in the order of her list', () => {
    expect(hers.find((c) => c.country === 'United Kingdom')?.pages.map((p) => p.sort)).toEqual([1, 2]);
  });

  it('lists the other countries that have a source, and only those', () => {
    expect(others.map((c) => c.country)).toEqual(['Egypt']);
  });
});

const item = (document_id: string, regulator_id: string, first_seen_at: string, extra: Partial<NewItem> = {}): NewItem => ({
  document_id,
  source_id: 'x',
  regulator_id,
  regulator_name: regulator_id,
  country_name: '',
  country_code: '',
  source_kind: 'safety',
  title_orig: document_id,
  lang: 'en',
  link: `https://example.test/${document_id}`,
  published_date: null,
  first_seen_at,
  doc_type: 'other',
  matched: false,
  r2_key: null,
  mime: null,
  email_id: null,
  email_r2_key: null,
  ...extra,
});

describe('new since you last looked', () => {
  const now = new Date('2026-11-06T10:00:00Z');
  const week = cairoWeekStart(now);

  it('counts from the last look at any authority of the country', () => {
    const looks = new Map([
      ['BFARM', '2026-11-03T08:00:00Z'],
      ['PEI', '2026-11-04T08:00:00Z'],
    ]);
    expect(lastLook({ regulators: REGULATORS.slice(0, 2) }, looks)).toBe('2026-11-04T08:00:00Z');
    expect(lastLook({ regulators: [REGULATORS[2]] }, looks)).toBeNull();
  });

  it("starts on this week's Sunday when she never looked, and never reaches back past a month", () => {
    expect(sinceFor(null, week, now)).toEqual(week);
    expect(sinceFor('2026-11-04T08:00:00Z', week, now).toISOString()).toBe('2026-11-04T08:00:00.000Z');
    expect(sinceFor('2026-10-28T08:00:00Z', week, now).toISOString()).toBe('2026-10-28T08:00:00.000Z');
    const floor = new Date(now.getTime() - MAX_LOOKBACK_DAYS * 86_400_000);
    expect(sinceFor('2026-01-01T00:00:00Z', week, now)).toEqual(floor);
  });

  it('lists the country’s items since then, newest first', () => {
    const items = [
      item('a', 'BFARM', '2026-11-02T08:00:00Z'),
      item('b', 'PEI', '2026-11-05T08:00:00Z'),
      item('c', 'BFARM', '2026-11-05T09:00:00Z'),
      item('d', 'MHRA', '2026-11-05T09:00:00Z'),
    ];
    const since = new Date('2026-11-04T08:00:00Z');
    expect(newSince(items, ['BFARM', 'PEI'], since).map((i) => i.document_id)).toEqual(['c', 'b']);
    // Germany since its look (c, b); the United Kingdom since Sunday (d); the others have nothing
    expect(totalNew(REGULATORS, items, new Map([['BFARM', '2026-11-04T08:00:00Z']]), week, now)).toBe(3);
  });
});

describe('pageStatus', () => {
  const sources = new Map<string, Pick<CardSource, 'enabled' | 'channel'>>([
    ['on', { enabled: true, channel: 'html' }],
    ['off', { enabled: false, channel: 'html' }],
    ['mail', { enabled: true, channel: 'email' }],
  ]);

  it('says plainly whether the app reads her page', () => {
    expect(pageStatus(page('X', 1, ['on']), sources).label).toBe('Read by the app');
    expect(pageStatus(page('X', 1, []), sources).label).toBe('Not read by the app — open it yourself');
    expect(pageStatus(page('X', 1, ['on'], { partial: true }), sources).state).toBe('partial');
  });

  it('counts a switched-off source as not reading the page', () => {
    expect(pageStatus(page('X', 1, ['off']), sources).state).toBe('unread');
    expect(pageStatus(page('X', 1, ['gone']), sources).state).toBe('unread');
  });

  it('names an e-mail subscription once', () => {
    const s = pageStatus(page('TGA', 3, ['mail'], { note: "By e-mail subscription: TGA's safety information e-mails." }), sources);
    expect(s.label).toBe('Read by the app, by e-mail subscription');
    expect(s.byEmail).toBe(true);
    expect(s.note).toBe("TGA's safety information e-mails.");
  });
});

describe('feed addresses', () => {
  it('are recognised and never become the page a person opens', () => {
    for (const u of [
      'https://www.gov.uk/drug-safety-update.atom',
      'https://api.fda.gov/drug/enforcement.json',
      'https://www.hsa.gov.sg/announcements/rss.xml',
      'https://www.basg.gv.at/whatsnew/rss',
      'https://www.aemps.gob.es/feed/',
      'https://www.bfarm.de/SiteGlobals/Functions/RSSFeed/DE/RSSNewsfeed.xml?nn=591002',
    ]) {
      expect(isFeedUrl(u)).toBe(true);
    }
    for (const u of ['https://www.gov.uk/drug-safety-update', 'https://www.fda.gov/', 'https://pubmed.ncbi.nlm.nih.gov/']) {
      expect(isFeedUrl(u)).toBe(false);
    }
    expect(sourcePage({ url: 'https://x.test/feed.xml', page_url: 'https://x.test/news' }, null)).toBe('https://x.test/news');
    expect(sourcePage({ url: 'https://x.test/list', page_url: null }, null)).toBe('https://x.test/list');
    expect(sourcePage({ url: 'https://x.test/feed.xml', page_url: null }, 'https://x.test/')).toBe('https://x.test/');
    expect(sourcePage({ url: 'https://x.test/feed.xml', page_url: null }, null)).toBeNull();
  });

  // new_items() in the database replaces a feed link by the source's page with the same rule.
  const MIGRATIONS = import.meta.glob('../../../../supabase/migrations/*.sql', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('follow the same rule as new_items() in the database', () => {
    const file = Object.keys(MIGRATIONS).find((f) => /function\s+new_items/.test(MIGRATIONS[f]));
    expect(file).toBeDefined();
    const inDb = /when d\.url ~\* '([^']+)' then\s+coalesce\(s\.page_url/.exec(MIGRATIONS[file as string])?.[1];
    expect(inDb).toBeDefined();
    expect(FEED_URL.source.replace(/\\\//g, '/')).toBe(inDb);
  });
});

describe('sourceLabel', () => {
  it('names a source by her page it reads, else by what it reads and where', () => {
    expect(sourceLabel(src('mhra-dsu', 'MHRA'), PAGES)).toBe('MHRA page 2');
    expect(sourceLabel(src('pmda-urgent', 'PMDA', { url: 'https://www.pmda.go.jp/safety/0001.html' }), [])).toBe(
      'Safety notices · pmda.go.jp',
    );
    expect(
      sourceLabel(src('fda-email', 'FDA', { channel: 'email', page_url: 'https://www.fda.gov/safety/medwatch' }), []),
    ).toBe('Safety notices by e-mail · fda.gov');
  });
});

describe('sourceLabels', () => {
  it('tells apart two sources of one card that would read the same', () => {
    const alerts = src('tga-alerts', 'TGA', { url: 'https://www.tga.gov.au/news/safety-alerts' });
    const updates = src('tga-updates', 'TGA', { url: 'https://www.tga.gov.au/news/safety-updates' });
    const mail = src('tga-email', 'TGA', { channel: 'email', url: 'https://www.tga.gov.au/news/safety-alerts' });
    const labels = sourceLabels([alerts, updates, mail], []);
    expect(labels.get('tga-alerts')).toBe('Safety notices · tga.gov.au · safety alerts');
    expect(labels.get('tga-updates')).toBe('Safety notices · tga.gov.au · safety updates');
    expect(labels.get('tga-email')).toBe('Safety notices by e-mail · tga.gov.au');
  });

  it('leaves a label alone when no other source of the card shares it', () => {
    const one = src('pmda-urgent', 'PMDA', { url: 'https://www.pmda.go.jp/safety/0001.html' });
    expect(sourceLabels([one], []).get('pmda-urgent')).toBe('Safety notices · pmda.go.jp');
  });
});

describe('offReason', () => {
  const note = "Switched off on purpose: TGA's site refuses our servers.";
  it('shows why a source is switched off, or why its site refuses it', () => {
    expect(offReason({ enabled: false, health: 'blocked', notes: note })).toBe(note);
    expect(offReason({ enabled: false, health: 'unknown', notes: note })).toBe(note);
    expect(offReason({ enabled: true, health: 'blocked', notes: note })).toBe(note);
  });

  it('keeps the catalogue notes of a source that is read to Technical details', () => {
    expect(offReason({ enabled: true, health: 'ok', notes: 'Read from the news API.' })).toBeNull();
    expect(offReason({ enabled: false, health: 'blocked', notes: null })).toBeNull();
    expect(offReason({ enabled: false, health: 'blocked', notes: '  ' })).toBeNull();
  });
});

describe('markLookedArgs', () => {
  it('stamps the time the list was read, so a notice that arrived while the card was open stays new', () => {
    // 6 Nov 2026 (finding 7 of the review of #103): the look was the time of the click
    const readAt = '2026-11-06T08:00:00.000Z';
    const args = markLookedArgs('BFARM', readAt);
    expect(args).toEqual({ p_regulator: 'BFARM', p_seen_to: readAt });
    const looks = new Map([['BFARM', args.p_seen_to]]);
    const arrived = item('late', 'BFARM', '2026-11-06T08:17:00.000Z');   // the 4-hourly run, card still open
    expect(newSince([arrived], ['BFARM'], new Date(lastLook({ regulators: [{ id: 'BFARM' } as CardRegulator] }, looks)!))
      .map((i) => i.document_id)).toEqual(['late']);
  });
});
