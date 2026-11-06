// The answer of ingredient_screen() and ingredient_papers() (migration 0039): one ingredient across every
// source, for a range of Cairo calendar days.

import type { DocType, IssueStatus, SourceChannel, SourceHealth, SourceKind } from '../../lib/types';
import type { RegulatorPage } from '../sources/horizontal';

export interface ScreenClass {
  id: string;
  code: string;
  name_en: string;
  origin: 'atc' | 'hand';
}

export interface ScreenIngredient {
  id: string;
  inn_en: string;
  atc_code: string | null;
  active: boolean;
  classes: ScreenClass[];
  /** How many names of the ingredient are looked for, and in how many languages. */
  names: number;
  name_languages: number;
  /** How many words of its drug classes are looked for, and in how many languages. */
  class_words: number;
  class_languages: number;
}

export interface ScreenSource {
  id: string;
  regulator_id: string;
  kind: SourceKind;
  channel: SourceChannel;
  url: string;
  page_url: string | null;
  enabled: boolean;
  health: SourceHealth;
  notes: string | null;
}

/** The latest decision on a notice. */
export interface Decision {
  to_status: IssueStatus;
  /** The full name of the person who recorded it. */
  person: string;
  at: string;
  comment: string | null;
}

/** A word that matched, as the notice wrote it, and the language of the word on the watchlist. */
export interface MatchedWord {
  text: string;
  lang: string | null;
}

/** One notice of an authority (or one label change) that names the ingredient or one of its classes. */
export interface Mention {
  document_id: string;
  source_id: string;
  regulator_id: string;
  regulator_name: string;
  country_name: string;
  country_code: string;
  /** The original title, never translated. */
  title: string;
  lang: string | null;
  /** A page a person opens; null for an e-mail with no web page (email_id and email_r2_key open it). */
  link: string | null;
  email_id: string | null;
  email_r2_key: string | null;
  /** The published day, else the Cairo day it was first seen (YYYY-MM-DD). */
  date: string;
  published_date: string | null;
  first_seen_at: string;
  doc_type: DocType;
  terms: MatchedWord[];
  /** Only words of a drug class matched, not the ingredient's own names. */
  by_class: boolean;
  /** History: found by a backfill or by the check of the past, never alerted. */
  is_backfill: boolean;
  /** Label changes only: the sections that changed. */
  sections: string[] | null;
  /** The notice it is filed under (not merely suggested for); null when it is not filed. */
  issue_id: string | null;
  issue_status: IssueStatus | null;
  decision: Decision | null;
}

export interface ScreenRegulator {
  id: string;
  name: string;
  country_name: string;
  country_code: string;
  homepage: string | null;
  /** On Dr Sama's list: it has pages of hers. */
  hers: boolean;
  /** Reads of its safety and recall sources in the days, and how many succeeded or failed. */
  runs: number;
  ok: number;
  failed: number;
  /** One of her safety or DHPC pages is read by no switched-on source. */
  unread_page: boolean;
  pages: RegulatorPage[];
  sources: ScreenSource[];
  mentions: Mention[];
}

export interface Paper {
  document_id: string;
  title: string;
  lang: string | null;
  journal: string | null;
  day: string;
  pubmed_url: string | null;
  pmc_url: string | null;
  by_class: boolean;
  is_backfill: boolean;
  first_seen_at: string;
}

/** One search the daily literature watch runs for this ingredient, and how many of the papers it found. */
export interface PaperQuery {
  query: string;
  kind: 'name' | 'class';
  pubmed: number;
  pmc: number;
}

export interface ScreenLiterature {
  papers: number;
  by_name: number;
  by_class: number;
  pubmed: number;
  pmc: number;
  by_query: PaperQuery[];
  /** The first 50 papers; ingredient_papers() gives the rest. */
  first: Paper[];
}

/** A report of a finding to the Egyptian Drug Authority (authority_report, 0041). */
export interface AuthoritySent {
  id: string;
  /** The day it was sent (YYYY-MM-DD). */
  on: string;
  reference: string | null;
  /** The full name of the person who recorded it. */
  person: string;
  note: string | null;
}

export type Clock = 'running' | 'late' | 'sent' | 'off';

/** The five-day clock of one notice, as finding_state() answers it (migrations 0041 and 0050). */
export interface FindingState {
  /** The Cairo day PHAROS first showed the notice — the day it was created in PHAROS (YYYY-MM-DD). */
  day_zero: string;
  /** Day zero plus the authority's days (5). */
  due: string;
  /** Days from today in Cairo to the due day; negative when late. */
  days_left: number;
  /** off: the latest decision is not Concerns us; sent: a report to the authority exists; late: past due; else running. */
  clock: Clock;
  /** The latest report to the authority not withdrawn, under whatever decision — never forgotten, even while off. */
  sent: AuthoritySent | null;
}

/** The clocks of the notices on the screen, by notice id. */
export type Findings = Record<string, FindingState>;

export interface IngredientScreenData {
  ingredient: ScreenIngredient;
  from: string;
  to: string;
  /** Hers first, then by country and name. */
  regulators: ScreenRegulator[];
  label_changes: Mention[];
  literature: ScreenLiterature;
  /** The five-day clock of every notice on the screen (finding_state, 0041), fetched with the screen. */
  findings: Findings;
}
