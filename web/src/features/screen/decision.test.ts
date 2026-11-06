import { describe, expect, it } from 'vitest';
import { choicesFor, isStaleDecision, needsReason, withDecision } from './decision';
import type { IngredientScreenData, Mention, ScreenRegulator } from './types';

const mention = (document_id: string, issue_id: string | null): Mention => ({
  document_id,
  source_id: 'src',
  regulator_id: 'R',
  regulator_name: 'R',
  country_name: 'X',
  country_code: 'XX',
  title: document_id,
  lang: 'en',
  link: null,
  email_id: null,
  email_r2_key: null,
  date: '2026-11-03',
  published_date: '2026-11-03',
  first_seen_at: '2026-11-03T08:00:00Z',
  doc_type: 'dhpc',
  terms: [],
  by_class: false,
  is_backfill: false,
  sections: null,
  issue_id,
  issue_status: issue_id ? 'new' : null,
  decision: null,
});

const reg = (id: string, mentions: Mention[]): ScreenRegulator => ({
  id,
  name: id,
  country_name: id,
  country_code: 'XX',
  homepage: null,
  hers: true,
  runs: 1,
  ok: 1,
  failed: 0,
  unread_page: false,
  pages: [],
  sources: [],
  mentions,
});

const DATA: IngredientScreenData = {
  ingredient: {
    id: 'i',
    inn_en: 'lornoxicam',
    atc_code: 'M01AC05',
    active: true,
    classes: [],
    names: 1,
    name_languages: 1,
    class_words: 0,
    class_languages: 0,
  },
  from: '2026-11-01',
  to: '2026-11-07',
  regulators: [reg('A', [mention('a1', 'n1'), mention('a2', 'n2')]), reg('B', [mention('b1', 'n1'), mention('b2', null)])],
  label_changes: [mention('l1', 'n1'), mention('l2', 'n3')],
  literature: { papers: 0, by_name: 0, by_class: 0, pubmed: 0, pmc: 0, by_query: [], first: [] },
};

describe('withDecision', () => {
  const decision = { to_status: 'relevant' as const, person: 'Dr Sama', at: '2026-11-06T10:00:00Z', comment: null };
  const after = withDecision(DATA, 'n1', decision);

  it('shows the decision on every mention filed under the same notice, in every country and label change', () => {
    const status = (ms: Mention[]) => ms.map((m) => m.issue_status);
    expect(status(after.regulators[0].mentions)).toEqual(['relevant', 'new']);
    expect(status(after.regulators[1].mentions)).toEqual(['relevant', null]);
    expect(status(after.label_changes)).toEqual(['relevant', 'new']);
    expect(after.regulators[1].mentions[0].decision).toEqual(decision);
    expect(after.regulators[1].mentions[1].decision).toBeNull();
  });

  it('leaves the screen it was given unchanged', () => {
    expect(DATA.regulators[0].mentions[0].issue_status).toBe('new');
    expect(DATA.label_changes[0].decision).toBeNull();
  });
});

describe('choices', () => {
  it('never offers New or the status the notice already has', () => {
    expect(choicesFor('new').map((c) => c.to)).toEqual(['reviewed', 'relevant', 'not_relevant']);
    expect(choicesFor('not_relevant').map((c) => c.to)).toEqual(['reviewed', 'relevant']);
  });

  it('asks for a reason only for Not relevant', () => {
    expect(needsReason('not_relevant')).toBe(true);
    expect(needsReason('relevant')).toBe(false);
    expect(needsReason(null)).toBe(false);
  });

  it('knows the refusal of a decision taken on an old status', () => {
    expect(isStaleDecision({ code: 'PH409', message: 'x' })).toBe(true);
    expect(isStaleDecision({ message: 'STALE_DECISION: someone else …' })).toBe(true);
    expect(isStaleDecision({ code: '42501', message: 'permission denied' })).toBe(false);
    expect(isStaleDecision(null)).toBe(false);
  });
});
