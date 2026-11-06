// The answer of ingredient_screen() and ingredient_papers() (migration 0039): one ingredient across every
// source, for a range of Cairo calendar days.

import type { DocType, IssueStatus, SourceChannel, SourceHealth, SourceKind } from '../../lib/types';
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
  /** Whether its English words are also searched on PubMed and PubMed Central (0051). */
  literature: boolean;
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

// ───────────────────────────── our label under "Label changes" (migration 0043) ─────────────────────────────

export type GapStatus = 'covered' | 'partly' | 'missing';

/** One sentence the originator added, set against the same section of our label. */
export interface GapSentence {
  sentence: string;
  status: GapStatus;
  /** Share of its content words found in our closest sentence, 0–1. */
  score: number;
  /** Our closest sentence, when any word is shared. */
  closest: string | null;
}

export interface GapSection {
  /** The originator's section as the label watch names it (4.4, us:warnings_and_precautions, ja:8). */
  section: string;
  /** The SmPC section of ours it was compared with. */
  our_section: string;
  /** Our label has that section. */
  our_text: boolean;
  covered: number;
  partly: number;
  missing: number;
  added: GapSentence[];
}

/** What the collector found for a label change against one version of our label (label_gap.gap). */
export interface LabelGap {
  /** False when the two labels are in different languages: nothing is compared, sections is empty. */
  lang_match: boolean;
  our_lang: string | null;
  their_lang: string | null;
  covered: number;
  partly: number;
  missing: number;
  sections: GapSection[];
}

/** One word-level change inside a section, as collectors/spc/diff.py stores it. */
export interface WordChange {
  op: 'insert' | 'delete' | 'replace';
  before: string;
  after: string;
  /** The words just before the change, to find the place. */
  context?: string;
}

export interface DiffSection {
  section: string;
  before: string | null;
  after: string | null;
  changes: WordChange[];
}

export interface LabelProduct {
  id: string;
  name: string;
  mah: string | null;
  country_code: string;
  country_name: string;
  source_id: string;
  regulator_id: string;
  regulator_name: string;
  url: string | null;
  /** The product whose label she follows first for this ingredient (one per ingredient). */
  is_reference: boolean;
}

/** The current version of our label the change was compared with. */
export interface OurLabelRef {
  id: string;
  product_name: string;
  version: string;
  lang: string;
  uploaded_at: string;
  /** The full name of the person who uploaded it. */
  uploaded_by: string | null;
}

/** One label change as label_changes() answers it. */
export interface LabelChange {
  change_id: string;
  detected_at: string;
  /** The Cairo day the change was detected (YYYY-MM-DD): the day the screen filters by. */
  detected_day: string;
  /** The date printed on the new label, and on the one before it. */
  label_date: string | null;
  previous_label_date: string | null;
  product: LabelProduct;
  lang: string | null;
  link: string | null;
  document_id: string | null;
  title: string;
  sections: string[];
  diff: DiffSection[];
  /** Null until the collector compared the change with our current label (within 4 hours of an upload). */
  gap: LabelGap | null;
  gap_at: string | null;
  /** Null when no label of ours is uploaded for the ingredient. */
  our_label: OurLabelRef | null;
  issue_id: string | null;
  issue_status: IssueStatus | null;
  is_backfill: boolean;
  decision: Decision | null;
}

/** A row of our_label as the Our label panel reads it. */
export interface OurLabelRow {
  id: string;
  ingredient_id: string;
  product_name: string;
  version: string;
  lang: string;
  sections: Record<string, string>;
  file_name: string | null;
  uploaded_by: string;
  uploaded_at: string;
  superseded_at: string | null;
}

/**
 * What the Label changes section holds in the cache. The decision buttons patch `label_changes` (one Mention per
 * change, keyed by change_id as document_id), `regulators` (always empty here) and `findings`, as they do on the
 * screen's own data.
 */
export interface LabelChangesData {
  changes: LabelChange[];
  regulators: ScreenRegulator[];
  label_changes: Mention[];
  findings: Findings;
}
