/**
 * The free terminologies (migration 0103): NCI Thesaurus, OAE, ICD-11 and MeSH, searched together. None of them is
 * MedDRA and none is claimed to be equivalent to it: a free code is kept on a reaction as `reaction.term`, never
 * sent in the E2B file, and a reaction without a MedDRA LLT says "Needs official MedDRA coding".
 */

export type TermSource = 'ncit' | 'oae' | 'icd11' | 'mesh';

export const TERM_SOURCES: readonly TermSource[] = ['ncit', 'oae', 'icd11', 'mesh'];

export const SOURCE_LABEL: Record<TermSource, string> = {
  ncit: 'NCI Thesaurus',
  oae: 'OAE',
  icd11: 'ICD-11',
  mesh: 'MeSH',
};

/** The credit each licence asks for, as the page and the case footer show it. */
export const SOURCE_CREDIT: Record<TermSource, string> = {
  ncit: 'NCI Thesaurus, the National Cancer Institute’s Enterprise Vocabulary Services (NCI does not endorse PHAROS)',
  oae: 'Ontology of Adverse Events (OAE), CC BY 4.0, without its MedDRA cross-references',
  icd11: 'ICD-11 MMS, World Health Organization, CC BY-ND 3.0 IGO, stored unchanged',
  mesh: 'MeSH, courtesy of the U.S. National Library of Medicine',
};

export interface TermHit {
  source: TermSource;
  code: string;
  name: string;
  found_as: string;
  status: 'current' | 'retired';
  match: 'code' | 'exact' | 'prefix' | 'trigram' | 'chosen';
  subsets: string[];
  chosen_before: number;
  score: number;
}

export interface TermConcept {
  source: TermSource;
  code: string;
  name: string;
  definition: string | null;
  lang: string;
  status: 'current' | 'retired';
  subsets: string[];
  uri: string | null;
  names: { name: string; lang: string; preferred: boolean }[];
  version: string | null;
  retired_in: string | null;
  source_name: string;
  licence: string;
  licence_url: string;
  attribution: string;
}

export interface TermChild {
  code: string;
  name: string;
  status: 'current' | 'retired';
  children: number;
}

export interface TermPathStep {
  depth: number;
  code: string;
  name: string;
}

export interface TermRelated {
  source: TermSource;
  code: string;
  name: string;
  same_words: string;
  note: string;
}

export interface TermRelease {
  id: number;
  source: TermSource;
  version: string;
  url: string | null;
  status: 'staged' | 'active' | 'superseded' | 'rejected';
  concepts: number;
  names: number;
  added: number;
  changed: number;
  retired: number;
  fetched_at: string;
  activated_at: string | null;
  note: string | null;
}

export interface TermChange {
  code: string;
  kind: 'added' | 'changed' | 'retired';
  before: { name?: string } | null;
  after: { name?: string } | null;
}

/** The free code kept on a reaction: who chose it and when, and the release it came from. */
export interface ReactionTerm {
  source: TermSource;
  code: string;
  name: string;
  version: string | null;
  coded_by: string;
  coded_at: string;
}

export const MATCH_LABEL: Record<TermHit['match'], string> = {
  code: 'code',
  exact: 'exact name',
  prefix: 'start of a name',
  trigram: 'close spelling',
  chosen: 'chosen before',
};

export function isTermSource(s: unknown): s is TermSource {
  return typeof s === 'string' && (TERM_SOURCES as readonly string[]).includes(s);
}

/** A reaction has an official MedDRA code only with an 8-digit LLT; anything else needs one. */
export function needsMeddra(r: { meddra_llt_code?: string | null } | null | undefined): boolean {
  return !/^\d{8}$/.test(String(r?.meddra_llt_code ?? '').trim());
}

/** A CTCAE grade among a concept's children ("Grade 2 Nausea, CTCAE 6.0"), with its number; or null. */
export function ctcaeGrade(name: string): number | null {
  const m = /^Grade ([1-5])\b.*CTCAE/i.exec(name.trim());
  return m ? Number(m[1]) : null;
}

/** The grades of a CTCAE term, in order; an empty list for any other concept. */
export function ctcaeGrades<T extends { name: string }>(children: T[]): (T & { grade: number })[] {
  return children
    .map((c) => ({ ...c, grade: ctcaeGrade(c.name) }))
    .filter((c): c is T & { grade: number } => c.grade !== null)
    .sort((a, b) => a.grade - b.grade);
}

/** The reaction with a free code chosen (or removed). A MeSH choice also fills the reaction's MeSH code, so the
 *  label checks (0062) see it; nothing else on the reaction changes, and the MedDRA fields are never touched. */
export function withTerm<R extends { mesh_ui?: string | null; mesh_term?: string | null; term?: ReactionTerm | null }>(
  r: R,
  term: ReactionTerm | null,
): R {
  if (!term) return { ...r, term: null };
  const out = { ...r, term };
  if (term.source === 'mesh') {
    out.mesh_ui = term.code;
    out.mesh_term = term.name;
  }
  return out;
}

/** The sources a case's reactions were coded from, for the credit line under them. */
export function sourcesUsed(reactions: { term?: ReactionTerm | null }[] | null | undefined): TermSource[] {
  const seen = new Set<TermSource>();
  for (const r of reactions ?? []) if (r.term && isTermSource(r.term.source)) seen.add(r.term.source);
  return TERM_SOURCES.filter((s) => seen.has(s));
}

/** The address of a concept's page. */
export function conceptPath(source: TermSource, code: string): string {
  return `/terminology/${source}/${encodeURIComponent(code)}`;
}
