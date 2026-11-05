// Row shapes as the web app reads them (supabase/migrations/0001_core.sql and 0002_ops.sql).

export type IssueStatus = 'new' | 'reviewed' | 'relevant' | 'not_relevant';
export type DocType =
  | 'dhpc'
  | 'safety_alert'
  | 'safety_update'
  | 'recall'
  | 'psusa'
  | 'label_change'
  | 'signal'
  | 'newsletter'
  | 'literature'
  | 'other';
export type PersonRole = 'admin' | 'reviewer' | 'reader';
export type LinkKind = 'anchor' | 'copy';
export type LinkMethod = 'auto' | 'suggested' | 'manual';
export type SourceKind = 'safety' | 'recall' | 'spc' | 'literature';
export type SourceChannel = 'rss' | 'atom' | 'json' | 'api' | 'html' | 'browser' | 'email';
export type SourceSchedule = '4h' | '12h' | 'daily' | 'weekly' | 'monthly';
export type SourceHealth = 'unknown' | 'ok' | 'degraded' | 'down' | 'blocked';
export type SourceOrigin = 'catalogue' | 'user';
export type TermKind = 'inn' | 'salt' | 'brand' | 'code' | 'synonym';
export type MatchMode = 'stem' | 'exact' | 'substring';
export type MatchField = 'structured' | 'title' | 'body' | 'attachment';
export type MatchConf = 'high' | 'possible';
export type SubKind = 'ingredient' | 'class_digest' | 'new_items_digest' | 'admin_health';
export type NotifKind = 'immediate' | 'digest' | 'health' | 'report' | 'escalation' | 'new_items_digest';
export type ExtractionKind = 'html' | 'text' | 'ocr' | 'none';
export type SignalStage = 'validation' | 'assessment' | 'action' | 'closed';
export type SignalPriority = 'high' | 'medium' | 'low';
export type SignalOutcome =
  | 'not_validated'
  | 'refuted'
  | 'monitor'
  | 'no_action'
  | 'label_update'
  | 'rmp_update'
  | 'dhpc'
  | 'psur_input';
export type SignalStep =
  | 'opened'
  | 'notice_linked'
  | 'validated'
  | 'not_validated'
  | 'prioritised'
  | 'assigned'
  | 'assessed'
  | 'action_done'
  | 'reopened'
  | 'note';

export const ISSUE_STATUSES: IssueStatus[] = ['new', 'reviewed', 'relevant', 'not_relevant'];
export const DOC_TYPES: DocType[] = [
  'dhpc',
  'safety_alert',
  'safety_update',
  'recall',
  'psusa',
  'label_change',
  'signal',
  'newsletter',
  'literature',
  'other',
];
export const SOURCE_CHANNELS: SourceChannel[] = ['rss', 'atom', 'json', 'api', 'html', 'browser', 'email'];
export const SOURCE_KINDS: SourceKind[] = ['safety', 'recall', 'spc', 'literature'];
export const SOURCE_SCHEDULES: SourceSchedule[] = ['4h', '12h', 'daily', 'weekly', 'monthly'];
export const TERM_KINDS: TermKind[] = ['inn', 'salt', 'brand', 'code', 'synonym'];
export const MATCH_MODES: MatchMode[] = ['stem', 'exact', 'substring'];
export const ROLES: PersonRole[] = ['admin', 'reviewer', 'reader'];
export const SIGNAL_STAGES: SignalStage[] = ['validation', 'assessment', 'action', 'closed'];
export const SIGNAL_PRIORITIES: SignalPriority[] = ['high', 'medium', 'low'];
/** Outcomes of an assessment that open an action with a due date; the others close the signal. */
export const ACTION_OUTCOMES: SignalOutcome[] = ['label_update', 'rmp_update', 'dhpc', 'psur_input'];
export const CLOSING_OUTCOMES: SignalOutcome[] = ['refuted', 'monitor', 'no_action'];

/** One row of the view v_issue_table. */
export interface IssueRow {
  id: string;
  first_date: string | null;
  doc_type: DocType;
  title: string;
  status: IssueStatus;
  class_only: boolean;
  is_backfill: boolean;
  link: string | null;
  anchor_country: string | null;
  anchor_regulator: string | null;
  countries: string[] | null;
  ingredients: string[] | null;
  copies: number;
  /** Language of the first notice, the one the title comes from. */
  lang: string | null;
}

export interface Person {
  id: string;
  auth_user_id: string | null;
  full_name: string;
  email: string | null;
  role: PersonRole;
  telegram_chat_id: number | null;
  telegram_linked_at: string | null;
  active: boolean;
  created_at: string;
}

export interface Regulator {
  id: string;
  country_code: string;
  country_name: string;
  name: string;
  languages: string[];
  homepage: string | null;
}

export interface Ingredient {
  id: string;
  inn_en: string;
  atc_code: string | null;
  wikidata_qid: string | null;
  rxcui: string | null;
  active: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_at: string;
}

export interface IngredientTerm {
  id: string;
  ingredient_id: string;
  lang: string;
  country_code: string | null;
  term: string;
  kind: TermKind;
  mode: MatchMode;
  exclusions: string[];
  source: string | null;
  verified_by: string | null;
  verified_at: string | null;
}

export interface Source {
  id: string;
  regulator_id: string;
  kind: SourceKind;
  channel: SourceChannel;
  url: string;
  parser: string;
  languages: string[];
  schedule: SourceSchedule;
  enabled: boolean;
  origin: SourceOrigin;
  health: SourceHealth;
  consecutive_failures: number;
  last_ok_at: string | null;
  last_item_at: string | null;
  expected_max_gap_days: number | null;
  notes: string | null;
  created_at: string;
}

export interface SourceRun {
  id: string;
  run_id: string;
  source_id: string;
  started_at: string;
  finished_at: string | null;
  http_status: number | null;
  items_seen: number;
  items_new: number;
  items_matched: number;
  error: string | null;
  duration_ms: number | null;
}

export interface DocumentRow {
  id: string;
  source_id: string;
  url: string;
  title_orig: string;
  lang: string | null;
  doc_type: DocType;
  published_date: string | null;
  first_seen_at: string;
  r2_key: string | null;
  mime: string | null;
  is_backfill: boolean;
}

export interface AttachmentRow {
  id: string;
  document_id: string;
  url: string;
  filename: string | null;
  r2_key: string | null;
  mime: string | null;
  bytes: number | null;
  extraction: ExtractionKind;
  words: number | null;
}

export interface DocumentTextRow {
  document_id: string;
  attachment_id: string | null;
  text: string;
}

export interface MatchRow {
  id: string;
  document_id: string;
  attachment_id: string | null;
  field: MatchField;
  start_offset: number | null;
  end_offset: number | null;
  matched_text: string;
  snippet: string | null;
  confidence: MatchConf;
  ingredient: { inn_en: string } | null;
  drug_class: { name_en: string } | null;
}

export interface ReviewEventRow {
  id: string;
  from_status: IssueStatus;
  to_status: IssueStatus;
  comment: string | null;
  created_at: string;
  person: { full_name: string } | null;
}

export interface NotificationRow {
  id: string;
  kind: NotifKind;
  dry_run: boolean;
  sent_at: string;
  error: string | null;
  summary: string | null;
  person: { full_name: string } | null;
}

export interface SubscriptionRow {
  id: string;
  person_id: string;
  kind: SubKind;
  ingredient_id: string | null;
  ingredient: { inn_en: string } | null;
}

export interface MonthlyReport {
  id: string;
  month: string;
  xlsx_r2_key: string;
  xlsx_sha256: string;
  pdf_r2_key: string;
  pdf_sha256: string;
  generated_at: string;
}

export interface ProbeResult {
  id: string;
  url: string;
  requested_at: string;
  status: 'queued' | 'running' | 'ok' | 'failed';
  channel_detected: string | null;
  parser_detected: string | null;
  items: unknown;
  error: string | null;
  finished_at: string | null;
}

/** ingredient-lookup {q} */
export interface LookupCandidate {
  inn_en: string;
  atc_code: string | null;
  wikidata_qid: string | null;
  rxcui: string | null;
  labels: Record<string, string>;
  sources: string[];
  score: number;
  /** Drug classes, when the lookup names them (e.g. ['NSAID']). */
  class_codes?: string[];
}

/** ingredient-lookup {action:'terms'} */
export interface LookupTerm {
  lang: string;
  country_code: string | null;
  term: string;
  kind: TermKind;
  mode: MatchMode;
  source: string | null;
}

/** One row of the view v_signal_table. */
export interface SignalRow {
  id: string;
  ref: string;
  title: string;
  stage: SignalStage;
  priority: SignalPriority | null;
  outcome: SignalOutcome | null;
  ingredient_id: string | null;
  ingredient: string | null;
  owner_id: string | null;
  owner: string | null;
  opened_at: string;
  closed_at: string | null;
  updated_at: string;
  validation_due: string;
  assessment_due: string | null;
  action_due: string | null;
  next_due: string | null;
  overdue: boolean;
  notices: number;
}

export interface SignalEventRow {
  id: string;
  step: SignalStep;
  from_stage: SignalStage | null;
  to_stage: SignalStage;
  priority: SignalPriority | null;
  outcome: SignalOutcome | null;
  due: string | null;
  comment: string | null;
  created_at: string;
  person: { full_name: string } | null;
  owner: { full_name: string } | null;
  issue_id: string | null;
}
