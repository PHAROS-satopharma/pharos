/**
 * The case form (safety_case.data, migration 0059) and the rules the Cases screens share with the database:
 * the four minimum criteria (caseMissing = case_missing() = collectors/cases/schema.py missing()), the clock
 * (caseDue = case_due()), and the words for each status and step.
 */

export type CaseStatus = 'queued' | 'reading' | 'to_confirm' | 'confirmed' | 'sent' | 'not_valid' | 'failed';
export type CaseOrigin = 'upload' | 'paper' | 'email';
export type CaseStep =
  | 'received'
  | 'read'
  | 'read_failed'
  | 'read_again'
  | 'saved'
  | 'confirmed'
  | 'not_valid'
  | 'sent'
  | 'reopened'
  | 'e2b_asked'
  | 'e2b_made'
  | 'e2b_failed'
  | 'note';

export interface Patient {
  initials?: string | null;
  age_value?: number | null;
  age_unit?: string | null;
  age_group?: string | null;
  sex?: string | null;
  birth_date?: string | null;
  weight_kg?: number | null;
  pregnant?: boolean | null;
  medical_history?: string | null;
  /** The medical history's conditions coded with MeSH (0061), chosen by a reviewer. */
  history_codes?: MeshCode[] | null;
}

/** A MeSH descriptor chosen for some words (0061). */
export interface MeshCode {
  text?: string | null;
  mesh_ui: string;
  mesh_term: string;
}

export interface Reporter {
  name?: string | null;
  qualification?: string | null;
  organisation?: string | null;
  country?: string | null;
  email?: string | null;
  phone?: string | null;
}

/** One active ingredient of a product with its amount (0099): from the product list, or as the document says. */
export interface ProductIngredient {
  name?: string | null;
  amount?: number | null;
  unit?: string | null;
}

export interface Product {
  name?: string | null;
  active_ingredient?: string | null;
  /** Each active ingredient with its amount (0099); the same shape as collectors/cases/schema.py INGREDIENT. */
  ingredients?: ProductIngredient[] | null;
  role?: string | null;
  dose?: string | null;
  route?: string | null;
  indication?: string | null;
  start_date?: string | null;
  stop_date?: string | null;
  action_taken?: string | null;
  batch?: string | null;
  /** RxNorm (ingredient level) and the ingredients' UNII, chosen by a reviewer (0061). */
  rxcui?: string | null;
  rxnorm_name?: string | null;
  unii?: string | null;
  indication_mesh_ui?: string | null;
  indication_mesh_term?: string | null;
}

export interface Reaction {
  verbatim?: string | null;
  verbatim_language?: string | null;
  english?: string | null;
  meddra_llt_code?: string | null;
  meddra_version?: string | null;
  /** The MeSH descriptor chosen by a reviewer (0061). */
  mesh_ui?: string | null;
  mesh_term?: string | null;
  onset_date?: string | null;
  end_date?: string | null;
  outcome?: string | null;
  serious?: boolean | null;
  criteria?: string[] | null;
}

export interface CaseForm {
  report_type?: string | null;
  received_date?: string | null;
  country?: string | null;
  literature_reference?: string | null;
  patient?: Patient | null;
  reporter?: Reporter | null;
  products?: Product[] | null;
  reactions?: Reaction[] | null;
  causality?: string | null;
  narrative?: string | null;
  notes?: string | null;
}

/** One suggested MeSH descriptor (safety_case.coding, collectors/coding/coder.py). */
export interface MeshSuggestion {
  ui: string;
  name: string;
  categories: string[];
  from: 'memory' | 'reader' | 'search';
  reason: string;
}

export interface DrugSuggestion {
  rxcui: string;
  name: string;
  tty: string;
  ingredients: { rxcui: string; name: string; unii: string | null }[];
  from: 'memory' | 'watchlist' | 'rxnorm';
  reason: string;
  ingredient_id?: string;
}

export interface CodedWords<S> {
  kind?: 'reaction' | 'indication' | 'history';
  index?: number | null;
  text: string;
  norm: string;
  suggestions: S[];
}

/** The coder's suggestions beside the form (safety_case.coding, migration 0061). */
export interface CaseCoding {
  at: string;
  mesh: string | null;
  reader: string | null;
  note: string | null;
  items: CodedWords<MeshSuggestion>[];
  history: CodedWords<MeshSuggestion>[];
  products: CodedWords<DrugSuggestion>[];
}

export const SUGGESTION_FROM: Record<MeshSuggestion['from'] | DrugSuggestion['from'], string> = {
  memory: 'Chosen before',
  reader: 'Suggested',
  search: 'Closest name',
  watchlist: 'On the watchlist',
  rxnorm: 'RxNorm',
};

/**
 * Words compared the way the coder and the database compare them (collectors/coding/norm.py, coding_norm()):
 * ASCII lower case, every run of characters other than ASCII letters, digits and non-ASCII letters one space.
 */
export function codingNorm(text: string | null | undefined): string {
  let low = '';
  for (const ch of text ?? '') low += ch < '\x80' ? ch.toLowerCase() : ch;
  return low.replace(/[^0-9a-z\u0080-\uffff]+/g, ' ').trim();
}

/** The suggestions made for these words, when the coder saw the same words. */
export function suggestionsFor<S>(list: CodedWords<S>[] | undefined, ...words: (string | null | undefined)[]): S[] | null {
  const wanted = new Set(words.map(codingNorm).filter(Boolean));
  const hit = (list ?? []).find((w) => wanted.has(w.norm));
  return hit ? hit.suggestions : null;
}

export interface Evidence {
  field: string;
  quote: string;
  page?: number | null;
}

export const STATUS_LABEL: Record<CaseStatus, string> = {
  queued: 'Waiting to be read',
  reading: 'Being read',
  to_confirm: 'To check and confirm',
  confirmed: 'Confirmed',
  sent: 'Sent to the authority',
  not_valid: 'Not a valid case',
  failed: 'Could not be read',
};

export const ORIGIN_LABEL: Record<CaseOrigin, string> = {
  upload: 'Uploaded',
  paper: 'Literature paper',
  email: 'Forwarded email',
};

export const STEP_LABEL: Record<CaseStep, string> = {
  received: 'Received',
  read: 'Read by PHAROS',
  read_failed: 'Could not be read',
  read_again: 'Asked to read again',
  saved: 'Saved',
  confirmed: 'Confirmed',
  not_valid: 'Marked not valid',
  sent: 'Sent to the authority',
  reopened: 'Reopened',
  e2b_asked: 'E2B file asked for',
  e2b_made: 'E2B file made',
  e2b_failed: 'E2B file not made',
  note: 'Note',
};

export const MISSING_LABEL: Record<string, string> = {
  patient: 'an identifiable patient',
  reporter: 'an identifiable reporter',
  product: 'a suspect product',
  reaction: 'a reaction',
};

export const SEX = [
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
];
export const AGE_UNIT = ['year', 'month', 'week', 'day', 'hour', 'decade'].map((v) => ({ value: v, label: `${v}s` }));
export const AGE_GROUP = ['neonate', 'infant', 'child', 'adolescent', 'adult', 'elderly'].map((v) => ({
  value: v,
  label: v[0].toUpperCase() + v.slice(1),
}));
export const QUALIFICATION = [
  { value: 'physician', label: 'Physician' },
  { value: 'pharmacist', label: 'Pharmacist' },
  { value: 'other_health_professional', label: 'Other health professional' },
  { value: 'lawyer', label: 'Lawyer' },
  { value: 'consumer', label: 'Patient or consumer' },
];
export const ROLE = [
  { value: 'suspect', label: 'Suspect' },
  { value: 'concomitant', label: 'Concomitant' },
  { value: 'interacting', label: 'Interacting' },
];
export const ACTION = [
  { value: 'withdrawn', label: 'Withdrawn' },
  { value: 'dose_reduced', label: 'Dose reduced' },
  { value: 'dose_increased', label: 'Dose increased' },
  { value: 'not_changed', label: 'Not changed' },
  { value: 'unknown', label: 'Unknown' },
  { value: 'not_applicable', label: 'Not applicable' },
];
export const OUTCOME = [
  { value: 'recovered', label: 'Recovered' },
  { value: 'recovering', label: 'Recovering' },
  { value: 'not_recovered', label: 'Not recovered' },
  { value: 'recovered_with_sequelae', label: 'Recovered with sequelae' },
  { value: 'fatal', label: 'Fatal' },
  { value: 'unknown', label: 'Unknown' },
];
export const CRITERIA = [
  { value: 'death', label: 'Death' },
  { value: 'life_threatening', label: 'Life-threatening' },
  { value: 'hospitalisation', label: 'Hospitalisation' },
  { value: 'disability', label: 'Disability' },
  { value: 'congenital_anomaly', label: 'Congenital anomaly' },
  { value: 'other_medically_important', label: 'Other medically important' },
];
export const REPORT_TYPE = [
  { value: 'spontaneous', label: 'Spontaneous' },
  { value: 'literature', label: 'Literature' },
  { value: 'study', label: 'Study' },
  { value: 'other', label: 'Other' },
];

/** The kinds of file the case-intake function takes (it checks the bytes again). */
export const ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.docx,.eml,.txt';
export const MAX_BYTES = 10 * 1024 * 1024;

function filled(v: unknown): boolean {
  return v !== null && v !== undefined && String(v).trim() !== '';
}

/** Which of the four minimum criteria (GVP Module VI) the form does not meet yet, in the database's order. */
export function caseMissing(form: CaseForm | null | undefined): string[] {
  const f = form ?? {};
  const p = f.patient ?? {};
  const r = f.reporter ?? {};
  const out: string[] = [];
  if (![p.initials, p.age_value, p.age_group, p.sex, p.birth_date].some(filled)) out.push('patient');
  if (![r.name, r.qualification, r.organisation, r.email, r.phone, f.literature_reference].some(filled)) {
    out.push('reporter');
  }
  if (!(f.products ?? []).some((x) => x.role === 'suspect' && filled(x.name))) out.push('product');
  if (!(f.reactions ?? []).some((x) => filled(x.verbatim))) out.push('reaction');
  return out;
}

/** 'YYYY-MM-DD' plus n days, in calendar days (no time zone involved). */
export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return t.toISOString().slice(0, 10);
}

/** The day the case is due at the authority: 15 days after day zero, 90 once a reviewer says it is not serious. */
export function caseDue(dayZero: string, serious: boolean | null | undefined): string {
  return addDays(dayZero, serious === false ? 90 : 15);
}

/** Whole days from today to the due day (negative when overdue). */
export function daysLeft(due: string, today: string): number {
  const ms = Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`);
  return Math.round(ms / 86400000);
}

export function clockLine(due: string, today: string, open: boolean): string {
  if (!open) return `Was due ${due}`;
  const n = daysLeft(due, today);
  if (n < 0) return `Overdue by ${-n} day${n === -1 ? '' : 's'} (due ${due})`;
  if (n === 0) return `Due today (${due})`;
  return `${n} day${n === 1 ? '' : 's'} left (due ${due})`;
}

/** Statuses whose clock still runs. */
export function isOpen(status: CaseStatus): boolean {
  return status === 'queued' || status === 'reading' || status === 'to_confirm' || status === 'failed' || status === 'confirmed';
}

/** An ingredient's unit as UCUM writes it in the E2B file (G.k.2.3.r.3b), the same map as collectors/cases/e2b.py. */
export const UCUM: Record<string, string> = {
  mg: 'mg',
  g: 'g',
  'µg': 'ug',
  mcg: 'ug',
  ug: 'ug',
  mL: 'mL',
  ml: 'mL',
  IU: '[iU]',
  '%': '%',
};

/** What an ingredient line of a product lacks for the E2B file (the same checks as e2b.py problems()). */
export function ingredientProblems(products: Product[] | null | undefined): string[] {
  const out: string[] = [];
  (products ?? []).forEach((p, k) => {
    if (!filled(p.name)) return;
    (p.ingredients ?? []).forEach((x, j) => {
      const said = `product ${k + 1} ingredient ${j + 1}`;
      const hasAmount = filled(x.amount);
      if (!filled(x.name)) {
        if (hasAmount) out.push(`${said} needs its name`);
        return;
      }
      if (!hasAmount) return;
      const n = Number(String(x.amount).trim());
      if (!Number.isFinite(n) || n <= 0) out.push(`${said}: the amount is not a number above zero`);
      if (!Object.prototype.hasOwnProperty.call(UCUM, String(x.unit ?? '').trim())) out.push(`${said} needs its unit (mg, g, µg, mL, IU or %)`);
    });
  });
  return out;
}

/** Why the E2B file cannot be made yet (the same checks as collectors/cases/e2b.py problems()). */
export function e2bProblems(form: CaseForm, serious: boolean | null, status: CaseStatus): string[] {
  const out = caseMissing(form).map((m) => `the case has no ${m} yet`);
  if (serious === null) out.push('seriousness is not decided');
  if (status !== 'confirmed' && status !== 'sent') out.push('the case is not confirmed');
  out.push(...ingredientProblems(form.products));
  (form.reactions ?? []).forEach((r, i) => {
    if (!filled(r.verbatim)) return;
    if (!/^\d{8}$/.test(String(r.meddra_llt_code ?? '').trim())) {
      out.push(`reaction ${i + 1} needs its MedDRA LLT code (8 digits)`);
    }
    if (!/^\d{1,2}\.\d$/.test(String(r.meddra_version ?? '').trim())) {
      out.push(`reaction ${i + 1} needs its MedDRA version (e.g. 28.1)`);
    }
  });
  return out;
}

/** A file as base64, for the case-intake function. */
export function toBase64(bytes: Uint8Array): string {
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

/** An empty string becomes null, so a cleared field is stored as "not stated". */
export function orNull(v: string): string | null {
  const t = v.trim();
  return t === '' ? null : t;
}

/** A number typed in a field, or null. */
export function numberOrNull(v: string): number | null {
  const t = v.trim().replace(',', '.');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}
