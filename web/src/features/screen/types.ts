// The answer of ingredient_screen() and ingredient_papers() (migration 0039): one ingredient across every
// source, for a range of Cairo calendar days.

import type {
  DocType,
  IssueStatus,
  SignalOutcome,
  SignalPriority,
  SignalStage,
  SignalStep,
  SourceChannel,
  SourceHealth,
  SourceKind,
} from '../../lib/types';
import type { RegulatorPage } from '../sources/horizontal';

/** What a class is to the ingredient (migration 0049): its group, the class above it, or a group added by hand. */
export type ScreenRelation = 'group' | 'parent' | 'manual';

export interface ScreenClass {
  id: string;
  code: string;
  name_en: string;
  origin: 'atc' | 'hand';
  relation: ScreenRelation;
  /** Whether its words are looked for. */
  enabled: boolean;
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
  /** How it was found: 'name' (its own names), else the nearest class whose word matched. */
  relation: 'name' | ScreenRelation;
  /** The class that found it; null when its own name did. */
  class_name: string | null;
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

/** Why a paper looks like a case report: PubMed lists it as one, or its title says so. */
export interface CaseReport {
  reason: 'pubtype' | 'title';
}

/** What a mention or a paper carries of its notice: enough for the decision buttons. */
export type Decided = Pick<Mention, 'issue_id' | 'issue_status' | 'decision'>;

/**
 * What paper_state() (migration 0044) says of one paper: its notice and decision, whether it looks like a
 * case report, and the clock: day zero is the Cairo day PHAROS found it, the dates are +15 and +90 days.
 */
export interface PaperState extends Decided {
  case_report: CaseReport | null;
  day_zero: string;
  due_serious: string;
  due_nonserious: string;
}

/** The states of the papers on screen, by document id. A paper not yet answered has no entry. */
export type PaperStates = Record<string, PaperState>;

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

/** One step of a signal, as signal_event holds it: who took it, when, and what they wrote. */
export interface SignalStepRow {
  step: SignalStep;
  from_stage: SignalStage | null;
  to_stage: SignalStage;
  priority: SignalPriority | null;
  outcome: SignalOutcome | null;
  /** The full name of the person who took it. */
  person: string;
  at: string;
  comment: string | null;
}

/** The step that moves a signal on from its stage; nothing once it is closed. */
export type SignalNextStep = 'validated' | 'assessed' | 'action_done';

/**
 * The signal a notice belongs to (migration 0042): opened by Concerns us, followed through validation,
 * assessment and action to closed. The database decides the stage and the due days; the screen shows them
 * and takes the next step through signal_take_step.
 */
export interface FindingSignal {
  id: string;
  /** SIG-2026-001, the name people use. */
  ref: string;
  title: string;
  stage: SignalStage;
  priority: SignalPriority | null;
  outcome: SignalOutcome | null;
  next_step: SignalNextStep | null;
  /** The Cairo day the current stage is due (YYYY-MM-DD); null once closed. */
  next_due: string | null;
  overdue: boolean;
  /** The full name of the owner, if one was assigned. */
  owner: string | null;
  opened_at: string;
  opened_by: string;
  /** Every step in order, the opening first. */
  steps: SignalStepRow[];
}

/** The five-day clock of one notice, as finding_state() answers it (migrations 0041, 0050 and 0042). */
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
  /** The signal the notice belongs to (0042), or null while none was opened. */
  signal: FindingSignal | null;
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
