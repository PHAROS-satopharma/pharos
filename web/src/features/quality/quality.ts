// The Quality tab (migration 0107): deviations (PV-SOP-021), audits (PV-SOP-022) and the one CAPA plan both
// feed. Pure helpers only: the words, the deadlines and the next steps. The database decides; these only say.

export type DeviationStatus = 'open' | 'investigating' | 'capa' | 'approved' | 'closed';
export type AuditStatus = 'planned' | 'report_received' | 'capa_submitted' | 'closed';
export type CapaStatus = 'draft' | 'approved' | 'in_progress' | 'done' | 'effective';
export type AuditKind = 'internal' | 'external';
export type Grade = 'critical' | 'major' | 'minor';
/** done; late (past and not done); soon (0–2 days left); running (more). */
export type DueState = 'done' | 'late' | 'soon' | 'running';
export type DeadlineKey = 'plan' | 'rfi' | 'review' | 'meeting' | 'draft' | 'approval' | 'submission';

export interface Due {
  due: string;
  done_on: string | null;
  days_left: number;
  state: DueState;
}
export interface Deadline extends Due {
  key: DeadlineKey;
}

export interface HistoryRow {
  kind: 'deviation' | 'audit' | 'observation' | 'capa';
  record_id: string;
  step: string;
  from_status: string | null;
  to_status: string | null;
  comment: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  person: string | null;
  at: string;
}

export interface Deviation {
  id: string;
  ref: string;
  year: number;
  serial: number;
  title: string;
  description: string;
  occurred_on: string | null;
  detected_on: string;
  level: 1 | 2 | 3 | null;
  patient_safety: boolean;
  regulatory_compliance: boolean;
  document_quality: boolean;
  inv_cause: string | null;
  inv_people_time: string | null;
  inv_reoccur: string | null;
  inv_similar: string | null;
  inv_other_impact: string | null;
  inv_training: string | null;
  root_cause: string | null;
  qa_satisfactory: boolean | null;
  status: DeviationStatus;
  created_by: string | null;
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
  history: HistoryRow[];
}

export interface Observation {
  id: string;
  number: number;
  text: string;
  grade: Grade;
  assigned_to: string | null;
  assigned_name: string | null;
  assigned_other: string | null;
  root_cause: string | null;
}

export interface Audit {
  id: string;
  kind: AuditKind;
  title: string;
  auditor: string;
  lead_auditor: string | null;
  planned_on: string | null;
  plan_sent_on: string | null;
  visit_from: string | null;
  visit_to: string | null;
  rfi_received_on: string | null;
  rfi_answered_on: string | null;
  report_received_on: string | null;
  reviewed_on: string | null;
  meeting_on: string | null;
  capa_drafted_on: string | null;
  capa_approved_on: string | null;
  capa_submitted_on: string | null;
  final_report_on: string | null;
  closure_confirmed_on: string | null;
  status: AuditStatus;
  created_by: string | null;
  created_at: string;
  deadlines: Deadline[];
  observations: Observation[];
  history: HistoryRow[];
}

export interface Capa {
  id: string;
  ref: string;
  year: number;
  serial: number;
  source: 'deviation' | 'audit';
  deviation_id: string | null;
  deviation_ref: string | null;
  observation_id: string | null;
  observation_number: number | null;
  audit_id: string | null;
  audit_title: string | null;
  audit_kind: AuditKind | null;
  corrective_action: string | null;
  preventive_action: string | null;
  owner_id: string | null;
  owner_other: string | null;
  owner_name: string | null;
  due_on: string | null;
  status: CapaStatus;
  evidence: string | null;
  done_on: string | null;
  verified_by: string | null;
  verified_at: string | null;
  created_by: string | null;
  created_at: string;
  due: Due | null;
  history: HistoryRow[];
}

/** A deadline PHAROS kept that passed unmet, proposed as a deviation for a reviewer to record or dismiss (0108). */
export type ProposalSource = 'eda_clock' | 'signal_step' | 'capa' | 'audit_deadline';
export type ProposalStatus = 'proposed' | 'confirmed' | 'dismissed';

export interface DeviationProposal {
  id: string;
  source_kind: ProposalSource;
  source_ref: string | null;
  ingredient_id: string | null;
  title: string;
  description: string;
  occurred_on: string;
  detected_on: string;
  patient_safety: boolean;
  regulatory_compliance: boolean;
  document_quality: boolean;
  status: ProposalStatus;
  dismissed_reason: string | null;
  deviation_id: string | null;
  deviation_ref: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export const PROPOSAL_SOURCE_LABEL: Record<ProposalSource, string> = {
  eda_clock: 'Five-day clock to the EDA',
  signal_step: 'Signal step',
  capa: 'CAPA due day',
  audit_deadline: 'Audit deadline (PV-SOP-022)',
};

/** The proposals still waiting for a decision, oldest miss first. */
export function waitingProposals(list: readonly DeviationProposal[]): DeviationProposal[] {
  return list
    .filter((p) => p.status === 'proposed')
    .sort((a, b) => a.occurred_on.localeCompare(b.occurred_on) || a.title.localeCompare(b.title));
}

/** "Was due Tue 3 Nov 2026 · found Wed 4 Nov 2026 (1 day late)". */
export function proposalDueText(p: Pick<DeviationProposal, 'occurred_on' | 'detected_on'>): string {
  const late = daysBetween(p.occurred_on, p.detected_on);
  return `Was due ${dayText(p.occurred_on)} · found ${dayText(p.detected_on)} (${daysWord(late)} late)`;
}

/** A drafted root cause and CAPA for a deviation or an audit observation (0109): text only, it changes no record. */
export type DraftKind = 'deviation' | 'observation';
export type DraftStatus = 'queued' | 'drafting' | 'ready' | 'failed';

export interface QualityDraft {
  id: string;
  record_kind: DraftKind;
  record_id: string;
  status: DraftStatus;
  root_cause: string | null;
  corrective_action: string | null;
  preventive_action: string | null;
  to_check: string | null;
  model: string | null;
  error: string | null;
  asked_by: string | null;
  asked_at: string;
  finished_at: string | null;
}

/** The latest draft of one record, or null. */
export function draftOf(list: readonly QualityDraft[], kind: DraftKind, id: string): QualityDraft | null {
  return list.find((d) => d.record_kind === kind && d.record_id === id) ?? null;
}

/** Still being drafted: asked for, not ready or failed yet. */
export function draftWaiting(d: Pick<QualityDraft, 'status'>): boolean {
  return d.status === 'queued' || d.status === 'drafting';
}

export interface QualityState {
  today: string;
  deviations: Deviation[];
  audits: Audit[];
  capas: Capa[];
}

// ───────────────────────────── words ─────────────────────────────

export const DEVIATION_STATUS_LABEL: Record<DeviationStatus, string> = {
  open: 'Recorded',
  investigating: 'Under investigation',
  capa: 'CAPA planned',
  approved: 'Approved by the QA Manager',
  closed: 'Closed',
};

export const AUDIT_STATUS_LABEL: Record<AuditStatus, string> = {
  planned: 'Planned',
  report_received: 'Report received',
  capa_submitted: 'CAPA submitted',
  closed: 'Closed',
};

export const CAPA_STATUS_LABEL: Record<CapaStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  in_progress: 'In progress',
  done: 'Done, to verify',
  effective: 'Effective (closed)',
};

export const LEVEL_LABEL: Record<1 | 2 | 3, { label: string; hint: string }> = {
  1: { label: 'Level 1', hint: 'The information readily shows no impact on patient safety or regulatory compliance.' },
  2: { label: 'Level 2', hint: 'May affect regulatory compliance; needs more investigation.' },
  3: { label: 'Level 3', hint: 'Impact on patient safety.' },
};

export const GRADE_LABEL: Record<Grade, string> = { critical: 'Critical', major: 'Major', minor: 'Minor' };

export const KIND_LABEL: Record<AuditKind, string> = { internal: 'Internal audit', external: 'External audit' };

/** The deadline's words, and the column of the audit the day it was done is kept in. */
export const DEADLINE: Record<DeadlineKey, { label: string; field: keyof Audit }> = {
  plan: { label: 'Audit plan to the QPPV', field: 'plan_sent_on' },
  rfi: { label: 'Answer to the request for information', field: 'rfi_answered_on' },
  review: { label: 'QPPV review of the report', field: 'reviewed_on' },
  meeting: { label: 'Meeting with the responsible persons', field: 'meeting_on' },
  draft: { label: 'Draft CAPA', field: 'capa_drafted_on' },
  approval: { label: 'All CAPAs reviewed and approved', field: 'capa_approved_on' },
  submission: { label: 'CAPA submitted', field: 'capa_submitted_on' },
};

/** The six investigation questions of PV-SOP-021, in her order, with the column each answer is kept in. */
export type InvestigationField =
  | 'inv_cause'
  | 'inv_people_time'
  | 'inv_reoccur'
  | 'inv_similar'
  | 'inv_other_impact'
  | 'inv_training';

export const INVESTIGATION: readonly { field: InvestigationField; question: string }[] = [
  { field: 'inv_cause', question: 'What was the cause?' },
  { field: 'inv_people_time', question: 'Who was involved, the time and the duration?' },
  { field: 'inv_reoccur', question: 'Could it reoccur?' },
  { field: 'inv_similar', question: 'Have similar deviations occurred in the past?' },
  { field: 'inv_other_impact', question: 'Any impact on other products or processes?' },
  { field: 'inv_training', question: 'Training status of the people involved?' },
];

// ───────────────────────────── days ─────────────────────────────

const WEEKDAY = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function parts(day: string): { y: number; m: number; d: number; w: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(day);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  return { y, m: mo, d, w: new Date(Date.UTC(y, mo - 1, d)).getUTCDay() };
}

/** "Thu 19 Nov 2026" for a Cairo calendar day (YYYY-MM-DD). */
export function dayText(day: string | null | undefined): string {
  if (!day) return '—';
  const p = parts(day);
  return p ? `${WEEKDAY[p.w]} ${p.d} ${MONTH[p.m - 1]} ${p.y}` : day;
}

/** "Thu 19 Nov", without the year. */
export function shortDay(day: string | null | undefined): string {
  if (!day) return '—';
  const p = parts(day);
  return p ? `${WEEKDAY[p.w]} ${p.d} ${MONTH[p.m - 1]}` : day;
}

/** Days from a to b (b − a), both calendar days. */
export function daysBetween(a: string, b: string): number {
  const pa = parts(a);
  const pb = parts(b);
  if (!pa || !pb) return 0;
  return Math.round((Date.UTC(pb.y, pb.m - 1, pb.d) - Date.UTC(pa.y, pa.m - 1, pa.d)) / 86_400_000);
}

export function daysWord(n: number): string {
  return `${n} ${n === 1 ? 'day' : 'days'}`;
}

function leftWords(daysLeft: number): string {
  if (daysLeft === 0) return 'due today';
  return `${daysWord(daysLeft)} left`;
}

/**
 * "Draft CAPA by Thu 19 Nov · 3 days left", "… · due today", "… · late by 2 days", or
 * "Draft CAPA done Tue 17 Nov" (with "· 2 days late" when it was done after its day).
 */
export function deadlineText(d: Deadline): string {
  const label = DEADLINE[d.key].label;
  if (d.state === 'done' && d.done_on) {
    const late = daysBetween(d.due, d.done_on);
    return `${label} done ${shortDay(d.done_on)}${late > 0 ? ` · ${daysWord(late)} late` : ''}`;
  }
  if (d.state === 'late') return `${label} by ${shortDay(d.due)} · late by ${daysWord(-d.days_left)}`;
  return `${label} by ${shortDay(d.due)} · ${leftWords(d.days_left)}`;
}

/** The deadline of an audit that comes next: the first not done, or none. */
export function nextDeadline(a: Pick<Audit, 'deadlines' | 'status'>): Deadline | null {
  if (a.status === 'closed') return null;
  return a.deadlines.find((d) => d.state !== 'done') ?? null;
}

/** "Due Thu 19 Nov · 3 days left", "Due Thu 19 Nov · late by 2 days", "Done Tue 17 Nov", "No due day yet". */
export function capaDueText(c: Pick<Capa, 'due' | 'due_on' | 'done_on' | 'status'>): string {
  if (c.status === 'done' || c.status === 'effective') return c.done_on ? `Done ${shortDay(c.done_on)}` : 'Done';
  if (!c.due || !c.due_on) return 'No due day yet';
  if (c.due.state === 'late') return `Due ${shortDay(c.due_on)} · late by ${daysWord(-c.due.days_left)}`;
  return `Due ${shortDay(c.due_on)} · ${leftWords(c.due.days_left)}`;
}

/** Where a CAPA comes from: "from D001/2026" or "from Audit Partner audit 2026, observation 2". */
export function capaSourceText(c: Pick<Capa, 'source' | 'deviation_ref' | 'audit_title' | 'observation_number'>): string {
  if (c.source === 'deviation') return `from ${c.deviation_ref ?? 'a deviation'}`;
  return `from Audit ${c.audit_title ?? ''}, observation ${c.observation_number ?? '?'}`;
}

// ───────────────────────────── the CAPA plan ─────────────────────────────

const RANK: Record<DueState | 'none', number> = { late: 0, soon: 1, running: 2, none: 3, done: 4 };

function rankOf(c: Capa): number {
  if (c.status === 'done' || c.status === 'effective') return RANK.done;
  return RANK[c.due?.state ?? 'none'];
}

/** Late ones first, then due within two days, then running, then with no due day, then done; by due day. */
export function sortCapas(list: readonly Capa[]): Capa[] {
  return [...list].sort(
    (a, b) =>
      rankOf(a) - rankOf(b) ||
      (a.due_on ?? '9999').localeCompare(b.due_on ?? '9999') ||
      a.year - b.year ||
      a.serial - b.serial,
  );
}

export type CapaStatusFilter = 'all' | 'open' | 'late' | CapaStatus;
export type CapaSourceFilter = 'all' | 'deviation' | 'audit';

export function filterCapas(list: readonly Capa[], status: CapaStatusFilter, source: CapaSourceFilter): Capa[] {
  return sortCapas(
    list.filter((c) => {
      if (source !== 'all' && c.source !== source) return false;
      if (status === 'all') return true;
      if (status === 'open') return c.status !== 'effective';
      if (status === 'late') return c.status !== 'done' && c.status !== 'effective' && c.due?.state === 'late';
      return c.status === status;
    }),
  );
}

/** The CAPAs of one deviation or one observation. */
export function capasOf(list: readonly Capa[], by: { deviation?: string; observation?: string }): Capa[] {
  return list.filter((c) =>
    by.deviation ? c.deviation_id === by.deviation : by.observation ? c.observation_id === by.observation : false,
  );
}

// ───────────────────────────── the next steps ─────────────────────────────

export interface Step<To extends string> {
  to: To;
  label: string;
  /** The comment is required (a judgement): the database refuses the step without one. */
  needsComment: boolean;
  /** Why the step cannot be taken yet, in her words; null when it can. */
  blocked: string | null;
  tone?: 'danger';
  /** Deviation, QA Manager: satisfactory (true) or not (false). */
  satisfactory?: boolean;
  /** Audit: the day it happened. */
  needsDay?: boolean;
  /** CAPA: the evidence and the day it was done. */
  needsEvidence?: boolean;
}

export function deviationSteps(
  d: Pick<Deviation, 'status' | 'level' | 'root_cause'>,
  capas: readonly Pick<Capa, 'status'>[],
): Step<'investigating' | 'capa' | 'approved' | 'closed'>[] {
  switch (d.status) {
    case 'open':
      return [{ to: 'investigating', label: 'Start the investigation', needsComment: false, blocked: null }];
    case 'investigating': {
      const missing = [d.level === null ? 'QA sets the level' : null, d.root_cause?.trim() ? null : 'give the root cause']
        .filter(Boolean)
        .join(' and ');
      return [
        {
          to: 'capa',
          label: 'Root cause found: plan the CAPA',
          needsComment: false,
          blocked: missing ? `First ${missing}.` : null,
        },
      ];
    }
    case 'capa':
      return [
        {
          to: 'approved',
          label: 'QA Manager: satisfactory, approve',
          needsComment: true,
          satisfactory: true,
          blocked: capas.length === 0 ? 'Add its CAPA first.' : null,
        },
        {
          to: 'approved',
          label: 'QA Manager: not satisfactory',
          needsComment: true,
          satisfactory: false,
          tone: 'danger',
          blocked: null,
        },
      ];
    case 'approved': {
      const open = capas.filter((c) => c.status !== 'effective').length;
      return [
        {
          to: 'closed',
          label: 'Close the deviation',
          needsComment: true,
          blocked: open > 0 ? `${open === 1 ? 'A CAPA is' : `${open} CAPAs are`} not effective yet.` : null,
        },
      ];
    }
    default:
      return [];
  }
}

export function auditSteps(
  a: Pick<Audit, 'status' | 'report_received_on' | 'closure_confirmed_on'>,
  capas: readonly Pick<Capa, 'status'>[],
): Step<'report_received' | 'capa_submitted' | 'closed'>[] {
  switch (a.status) {
    case 'planned':
      return [{ to: 'report_received', label: 'The audit report was received', needsComment: false, needsDay: true, blocked: null }];
    case 'report_received':
      return [{ to: 'capa_submitted', label: 'The CAPA was submitted', needsComment: false, needsDay: true, blocked: null }];
    case 'capa_submitted': {
      const open = capas.filter((c) => c.status !== 'effective').length;
      return [
        {
          to: 'closed',
          label: 'Closure confirmed: close the audit',
          needsComment: true,
          needsDay: true,
          blocked: open > 0 ? `${open === 1 ? 'A CAPA is' : `${open} CAPAs are`} not effective yet.` : null,
        },
      ];
    }
    default:
      return [];
  }
}

export function capaSteps(
  c: Pick<Capa, 'status' | 'owner_id' | 'owner_other' | 'due_on'>,
): Step<'approved' | 'in_progress' | 'done' | 'effective' | 'not_effective'>[] {
  switch (c.status) {
    case 'draft':
      return [
        {
          to: 'approved',
          label: 'Approve the CAPA',
          needsComment: true,
          blocked: !c.due_on || (!c.owner_id && !c.owner_other?.trim()) ? 'Give it an owner and a due day first.' : null,
        },
      ];
    case 'approved':
      return [{ to: 'in_progress', label: 'Start the work', needsComment: false, blocked: null }];
    case 'in_progress':
      return [{ to: 'done', label: 'Done: add the evidence', needsComment: false, needsEvidence: true, blocked: null }];
    case 'done':
      return [
        { to: 'effective', label: 'Verified effective', needsComment: true, blocked: null },
        { to: 'not_effective', label: 'Not effective: back to work', needsComment: true, tone: 'danger', blocked: null },
      ];
    default:
      return [];
  }
}

// ───────────────────────────── the history ─────────────────────────────

const STEP_WORDS: Record<string, string> = {
  opened: 'Recorded',
  updated: 'Changed',
  level_set: 'Level set',
  investigating: 'Investigation started',
  capa: 'Root cause found, CAPA planned',
  approved: 'Approved',
  not_satisfactory: 'Not satisfactory: back to the investigation',
  closed: 'Closed',
  report_received: 'Report received',
  capa_submitted: 'CAPA submitted',
  in_progress: 'Work started',
  done: 'Done',
  effective: 'Verified effective',
  not_effective: 'Not effective: back to work',
};

const FIELD_WORDS: Record<string, string> = {
  title: 'title',
  description: 'description',
  occurred_on: 'day it happened',
  detected_on: 'day detected',
  level: 'level',
  patient_safety: 'patient safety',
  regulatory_compliance: 'regulatory compliance',
  document_quality: 'document quality',
  inv_cause: 'cause',
  inv_people_time: 'who, when and how long',
  inv_reoccur: 'could it reoccur',
  inv_similar: 'similar deviations',
  inv_other_impact: 'impact on other products',
  inv_training: 'training status',
  root_cause: 'root cause',
  auditor: 'auditor',
  lead_auditor: 'lead auditor',
  planned_on: 'planned day',
  plan_sent_on: 'audit plan sent',
  visit_from: 'visit from',
  visit_to: 'visit to',
  rfi_received_on: 'request for information received',
  rfi_answered_on: 'request for information answered',
  report_received_on: 'report received',
  reviewed_on: 'QPPV review',
  meeting_on: 'meeting',
  capa_drafted_on: 'draft CAPA',
  capa_approved_on: 'CAPAs approved',
  capa_submitted_on: 'CAPA submitted',
  final_report_on: 'final report',
  closure_confirmed_on: 'closure confirmed',
  text: 'observation',
  grade: 'grade',
  assigned_to: 'stakeholder',
  assigned_other: 'stakeholder outside PHAROS',
  corrective_action: 'corrective action',
  preventive_action: 'preventive action',
  owner_id: 'owner',
  owner_other: 'owner outside PHAROS',
  due_on: 'due day',
  evidence: 'evidence',
  done_on: 'day done',
  qa_satisfactory: 'QA satisfactory',
};

/** "Changed: root cause, due day" — the step in words, with the fields a change touched. */
export function historyWords(h: Pick<HistoryRow, 'step' | 'after' | 'kind'>): string {
  const step = h.kind === 'observation' && h.step === 'opened' ? 'Observation added' : (STEP_WORDS[h.step] ?? h.step);
  if (h.step === 'updated' && h.after) {
    const fields = Object.keys(h.after).map((k) => FIELD_WORDS[k] ?? k.replace(/_/g, ' '));
    if (fields.length) return `${step}: ${fields.join(', ')}`;
  }
  if (h.step === 'level_set' && h.after && typeof h.after.level === 'number') return `Level set to ${h.after.level}`;
  return step;
}

/** A refused write because the record moved meanwhile (PH409 STALE_QUALITY). */
export function isStale(error: { code?: string; message?: string } | null | undefined): boolean {
  if (!error) return false;
  return error.code === 'PH409' || (error.message ?? '').startsWith('STALE_QUALITY');
}

/** The counts on the head of each section. */
export function capaCounts(list: readonly Capa[]): { open: number; late: number; effective: number } {
  let open = 0;
  let late = 0;
  let effective = 0;
  for (const c of list) {
    if (c.status === 'effective') effective += 1;
    else {
      open += 1;
      if (c.status !== 'done' && c.due?.state === 'late') late += 1;
    }
  }
  return { open, late, effective };
}
