// The papers on the Ingredients screen: what paper_state() (migration 0044) says of each, in her words.
// Pure functions; the hooks are in paperState.ts.

import type { CaseReport, Decision, PaperPage, PaperState, PaperStates } from './types';

export type { PaperState, PaperStates } from './types';

/** Why a paper looks like a case report. */
export function caseReportLabel(c: CaseReport): string {
  return c.reason === 'pubtype' ? 'PubMed lists it as a case report' : 'Its title says so';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "5 Nov 2026", or "5 Nov" when the year is the one given. */
function dayWords(ymd: string, omitYear?: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd);
  if (!m) return ymd;
  const year = Number(m[1]);
  const text = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}`;
  return year === omitYear ? text : `${text} ${year}`;
}

/**
 * Day zero (the Cairo day PHAROS found the paper) and the dates to report a valid case: 15 days if serious,
 * 90 if not. The year is written on day zero, and again only on a date in another year.
 */
export function dueLine(s: PaperState): string {
  const year = Number(s.day_zero.slice(0, 4));
  return `day zero ${dayWords(s.day_zero)} · 15 days: ${dayWords(s.due_serious, year)} · 90 days: ${dayWords(s.due_nonserious, year)}`;
}

/** The possible case reports first; otherwise the order the screen gave. A paper with no state yet stays put. */
export function orderPapers<T extends { document_id: string }>(papers: T[], states: PaperStates): T[] {
  const isCase = (p: T) => Boolean(states[p.document_id]?.case_report);
  return [...papers.filter(isCase), ...papers.filter((p) => !isCase(p))];
}

/** A decision on a notice, shown at once on every paper filed under it. The given states are never changed. */
export function withPaperDecision(states: PaperStates, issueId: string, d: Decision): PaperStates {
  const out: PaperStates = {};
  for (const [id, s] of Object.entries(states)) {
    out[id] = s.issue_id === issueId ? { ...s, issue_status: d.to_status, decision: d } : s;
  }
  return out;
}

/** The notices the papers are filed under, each once: what finding_state() is asked for, page by page. */
export function paperIssueIds(states: PaperStates): string[] {
  const ids = new Set<string>();
  for (const s of Object.values(states)) if (s.issue_id) ids.add(s.issue_id);
  return [...ids];
}

/** Every page loaded, as one: the states of all its papers and the clocks of their notices. A page whose answer has
 *  not arrived yet is left out. */
export function mergePaperPages(pages: (PaperPage | undefined)[]): PaperPage {
  const out: PaperPage = { states: {}, findings: {} };
  for (const p of pages) {
    if (!p) continue;
    Object.assign(out.states, p.states);
    Object.assign(out.findings, p.findings);
  }
  return out;
}

/** Pieces of at most n, in order. */
export function chunk<T>(xs: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}

/** Whether EMA reads the literature for this ingredient (its medical literature monitoring list), in plain words. */
export function mlmLabel(monitored: boolean | undefined): { label: string; explain: string } | null {
  if (monitored === undefined) return null;
  return monitored
    ? {
        label: 'Monitored by EMA (MLM)',
        explain: "EMA's medical literature monitoring reads the literature for this ingredient and enters the cases it finds.",
      }
    : {
        label: 'Not monitored by EMA',
        explain: 'EMA does not read the literature for this ingredient: cases in the literature are ours to report.',
      };
}
