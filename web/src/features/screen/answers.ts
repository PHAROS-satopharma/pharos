// The answer for each country on the Ingredients screen: was the ingredient mentioned, was nothing found, or
// must she check it by hand because the app could not read it. Pure helpers, no I/O.

import { countryCards, type RegulatorPage } from '../sources/horizontal';
import type { Mention, ScreenRegulator, ScreenSource } from './types';

/** In the order the screen shows them: what needs her eyes first. */
export type Answer = 'mentioned' | 'not_read' | 'failed' | 'unread_page' | 'fine';

export const ANSWER_RANK: Record<Answer, number> = {
  mentioned: 0,
  not_read: 1,
  failed: 2,
  unread_page: 3,
  fine: 4,
};

export interface CountryAnswer {
  country: string;
  code: string | null;
  /** On her list: one of its authorities has pages of hers. */
  hers: boolean;
  regulators: ScreenRegulator[];
  pages: RegulatorPage[];
  sources: ScreenSource[];
  /** Every mention by its authorities, newest first. */
  mentions: Mention[];
  runs: number;
  ok: number;
  failed: number;
  unreadPage: boolean;
  answer: Answer;
}

/** Nothing found is an answer only when the app read the country and could read every page of hers. */
export function answerOf(c: { mentions: unknown[]; runs: number; failed: number; unreadPage: boolean }): Answer {
  if (c.mentions.length > 0) return 'mentioned';
  if (c.runs === 0) return 'not_read';
  if (c.failed > 0) return 'failed';
  if (c.unreadPage) return 'unread_page';
  return 'fine';
}

export function toCheckByHand(a: Answer): boolean {
  return a === 'not_read' || a === 'failed' || a === 'unread_page';
}

export function byNewest(a: Mention, b: Mention): number {
  return (
    b.date.localeCompare(a.date) ||
    Date.parse(b.first_seen_at) - Date.parse(a.first_seen_at) ||
    a.document_id.localeCompare(b.document_id)
  );
}

/**
 * One answer per country, as the Sources screen groups them: her countries, then other authorities. Within
 * each, mentions first, then what she must check by hand, then nothing found; A to Z within an answer.
 */
export function countryAnswers(regulators: ScreenRegulator[]): { hers: CountryAnswer[]; others: CountryAnswer[] } {
  const byId = new Map(regulators.map((r) => [r.id, r]));
  const { hers, others } = countryCards(
    regulators,
    regulators.flatMap((r) => r.pages),
    regulators.flatMap((r) => r.sources),
  );
  const toAnswer = (hersCard: boolean) => (card: (typeof hers)[number]): CountryAnswer => {
    const regs = card.regulators.map((r) => byId.get(r.id)).filter((r): r is ScreenRegulator => Boolean(r));
    const mentions = regs.flatMap((r) => r.mentions).sort(byNewest);
    const runs = regs.reduce((n, r) => n + r.runs, 0);
    const ok = regs.reduce((n, r) => n + r.ok, 0);
    const failed = regs.reduce((n, r) => n + r.failed, 0);
    const unreadPage = regs.some((r) => r.unread_page);
    return {
      country: card.country,
      code: card.code,
      hers: hersCard,
      regulators: regs,
      pages: card.pages,
      sources: card.sources,
      mentions,
      runs,
      ok,
      failed,
      unreadPage,
      answer: answerOf({ mentions, runs, failed, unreadPage }),
    };
  };
  const order = (a: CountryAnswer, b: CountryAnswer) =>
    ANSWER_RANK[a.answer] - ANSWER_RANK[b.answer] || a.country.localeCompare(b.country);
  return { hers: hers.map(toAnswer(true)).sort(order), others: others.map(toAnswer(false)).sort(order) };
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The answer in one line. */
export function answerText(c: CountryAnswer): string {
  switch (c.answer) {
    case 'mentioned':
      return `Mentioned in ${plural(c.mentions.length, 'notice', 'notices')}`;
    case 'not_read':
      return 'Not read in these days — check it by hand';
    case 'failed':
      return `${c.failed} of ${plural(c.runs, 'read', 'reads')} failed — check it by hand`;
    case 'unread_page':
      return 'A page of hers is not read by the app — check it by hand';
    default:
      return 'Nothing found';
  }
}

/** How the app read the country in those days. */
export function readsText(c: Pick<CountryAnswer, 'runs' | 'failed'>): string {
  if (c.runs === 0) return 'Not read in these days';
  const read = `Read ${plural(c.runs, 'time', 'times')} in these days`;
  return c.failed > 0 ? `${read}, ${c.failed} failed` : read;
}

/** "Mentioned in 2 of 25 countries · 20 nothing found · 3 to check by hand". */
export function summaryLine(countries: CountryAnswer[]): string {
  const mentioned = countries.filter((c) => c.answer === 'mentioned').length;
  const fine = countries.filter((c) => c.answer === 'fine').length;
  const check = countries.filter((c) => toCheckByHand(c.answer)).length;
  return `Mentioned in ${mentioned} of ${plural(countries.length, 'country', 'countries')} · ${fine} nothing found · ${check} to check by hand`;
}
