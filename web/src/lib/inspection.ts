import { supabase } from './supabase';
import { fetchAllPages, unwrap } from './api';
import { personNames } from './people';
import { downloadBlob } from './download';
import { cairoMidnightUtc, cairoToday, formatCairoDate, formatDate, formatDateTime } from './format';
import {
  CHANNEL_LABEL,
  DOC_TYPE_LABEL,
  HEALTH_LABEL,
  KIND_LABEL,
  NOTIF_KIND_LABEL,
  ROLE_LABEL,
  SCHEDULE_LABEL,
  SIGNAL_OUTCOME_LABEL,
  SIGNAL_PRIORITY_LABEL,
  SIGNAL_STAGE_LABEL,
  SIGNAL_STEP_LABEL,
  STATUS_LABEL,
} from './labels';
import type {
  DocType,
  IssueStatus,
  NotifKind,
  PersonRole,
  SignalRow,
  SignalStep,
  SourceChannel,
  SourceHealth,
  SourceKind,
  SourceSchedule,
} from './types';

type ExcelModule = typeof import('exceljs');
type Worksheet = import('exceljs').Worksheet;

async function loadExcel(): Promise<ExcelModule> {
  const mod = await import('exceljs');
  const withDefault = mod as unknown as { default?: ExcelModule };
  return withDefault.default ?? mod;
}

const INK = 'FF02224C';
const LINE = 'FFD9D5CC';
const OK_FILL = 'FFE7EEF0';
const OK_TEXT = 'FF1F4E5F';
const FAIL_FILL = 'FFF7E9E7';
const FAIL_TEXT = 'FFA8322D';
const NONE_FILL = 'FFF6F4EF';

/** Every Cairo calendar day from `from` to `to`, inclusive (YYYY-MM-DD). */
export function daysBetween(from: string, to: string): string[] {
  const out: string[] = [];
  const [fy, fm, fd] = from.split('-').map(Number);
  const [ty, tm, td] = to.split('-').map(Number);
  const end = Date.UTC(ty, tm - 1, td);
  for (let t = Date.UTC(fy, fm - 1, fd); t <= end; t += 86_400_000) out.push(new Date(t).toISOString().slice(0, 10));
  return out;
}

/** Hours between two instants, one decimal; null when either is missing. */
export function hoursBetween(a: string | null, b: string | null): number | null {
  if (!a || !b) return null;
  const h = (new Date(b).getTime() - new Date(a).getTime()) / 3_600_000;
  return Number.isFinite(h) ? Math.round(h * 10) / 10 : null;
}

/** The middle value (the mean of the two middle values for an even count); null for none. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((x, y) => x - y);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round(((s[mid - 1] + s[mid]) / 2) * 10) / 10;
}

/** What an audit row changed, in a few words: the fields an update changed, or created / removed. */
export function auditChange(action: string, oldRow: unknown, newRow: unknown): string {
  if (action === 'INSERT') return 'Created';
  if (action === 'DELETE') return 'Removed';
  const o = (oldRow ?? {}) as Record<string, unknown>;
  const n = (newRow ?? {}) as Record<string, unknown>;
  const changed = Object.keys({ ...o, ...n }).filter(
    (k) => k !== 'updated_at' && JSON.stringify(o[k]) !== JSON.stringify(n[k]),
  );
  return changed.length ? `Changed ${changed.join(', ')}` : 'No field changed';
}

interface SourceInfo {
  id: string;
  kind: SourceKind;
  channel: SourceChannel;
  url: string;
  schedule: SourceSchedule;
  enabled: boolean;
  health: SourceHealth;
  origin: string;
  last_ok_at: string | null;
  created_at: string;
  regulator: { name: string; country_name: string } | null;
}

interface CoverageRow {
  source_id: string;
  day: string;
  runs: number;
  ok_runs: number;
  failed_runs: number;
  items_seen: number;
  items_matched: number;
}

interface IssueInfo {
  id: string;
  created_at: string;
  first_date: string | null;
  doc_type: DocType;
  title: string;
  status: IssueStatus;
  class_only: boolean;
}

interface ReviewInfo {
  issue_id: string;
  from_status: IssueStatus;
  to_status: IssueStatus;
  comment: string | null;
  person_id: string;
  created_at: string;
}

function headRow(ws: Worksheet, columns: { header: string; key: string; width: number }[]) {
  ws.columns = columns;
  const head = ws.getRow(1);
  head.font = { bold: true, color: { argb: INK } };
  head.border = { bottom: { style: 'thin', color: { argb: INK } } };
  head.alignment = { vertical: 'middle', wrapText: true };
  head.height = 30;
  ws.views = [{ state: 'frozen', ySplit: 1 }];
  ws.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: columns.length } };
}

function ruled(ws: Worksheet) {
  ws.eachRow((row, i) => {
    if (i === 1) return;
    row.alignment = { vertical: 'top', wrapText: true };
    row.border = { bottom: { style: 'thin', color: { argb: LINE } } };
  });
}

function inChunks<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export interface PackProgress {
  (step: string): void;
}

/**
 * Builds the inspection pack for a Cairo period and downloads it. Administrators only: the database refuses
 * the coverage calendar to anyone else, and the audit trail and alerts are theirs to read.
 */
export async function buildInspectionPack(from: string, to: string, by: string, progress: PackProgress): Promise<void> {
  const fromUtc = cairoMidnightUtc(...(from.split('-').map(Number) as [number, number, number])).toISOString();
  const [ty, tm, td] = to.split('-').map(Number);
  const toUtc = cairoMidnightUtc(ty, tm, td + 1).toISOString();
  const days = daysBetween(from, to);

  progress('Reading the sources and the coverage');
  const [sources, coverage] = await Promise.all([
    fetchAllPages<SourceInfo>(async (a, b) =>
      await supabase
        .from('source')
        .select('id,kind,channel,url,schedule,enabled,health,origin,last_ok_at,created_at,regulator:regulator_id(name,country_name)')
        .order('id')
        .range(a, b),
    ),
    (async () =>
      (unwrap<CoverageRow[] | null>(await supabase.rpc('inspection_coverage', { p_from: from, p_to: to })) ?? []).map((r) => ({
        ...r,
        runs: Number(r.runs),
        ok_runs: Number(r.ok_runs),
        failed_runs: Number(r.failed_runs),
        items_seen: Number(r.items_seen),
        items_matched: Number(r.items_matched),
      })))(),
  ]);

  progress('Reading the notices and the decisions');
  const [issues, reviews] = await Promise.all([
    fetchAllPages<IssueInfo>(async (a, b) =>
      await supabase
        .from('issue')
        .select('id,created_at,first_date,doc_type,title,status,class_only')
        .eq('is_backfill', false)
        .gte('created_at', fromUtc)
        .lt('created_at', toUtc)
        .order('created_at')
        .range(a, b),
    ),
    fetchAllPages<ReviewInfo>(async (a, b) =>
      await supabase
        .from('review_event')
        .select('issue_id,from_status,to_status,comment,person_id,created_at')
        .gte('created_at', fromUtc)
        .lt('created_at', toUtc)
        .order('created_at')
        .range(a, b),
    ),
  ]);
  // The first decision on each notice found in the period, even when it came after the period ended.
  const firstDecision = new Map<string, string>();
  for (const chunk of inChunks(issues.map((i) => i.id), 200)) {
    const rows =
      unwrap<{ issue_id: string; created_at: string }[] | null>(
        await supabase.from('review_event').select('issue_id,created_at').in('issue_id', chunk).order('created_at'),
      ) ?? [];
    for (const r of rows) if (!firstDecision.has(r.issue_id)) firstDecision.set(r.issue_id, r.created_at);
  }
  // Countries and ingredients of the notices in the period, and of the notices decided in it.
  const issueIds = Array.from(new Set([...issues.map((i) => i.id), ...reviews.map((r) => r.issue_id)]));
  const issueView = new Map<string, { anchor_country: string | null; anchor_regulator: string | null; ingredients: string[] | null; title: string; link: string | null }>();
  for (const chunk of inChunks(issueIds, 200)) {
    const rows =
      unwrap<{ id: string; anchor_country: string | null; anchor_regulator: string | null; ingredients: string[] | null; title: string; link: string | null }[] | null>(
        await supabase.from('v_issue_table').select('id,anchor_country,anchor_regulator,ingredients,title,link').in('id', chunk),
      ) ?? [];
    for (const r of rows) issueView.set(r.id, r);
  }

  progress('Reading the signals, alerts and audit trail');
  const [signals, signalEvents, alerts, audit, checks, people, watch] = await Promise.all([
    fetchAllPages<SignalRow>(async (a, b) =>
      await supabase
        .from('v_signal_table')
        .select('id,ref,title,stage,priority,outcome,ingredient,owner,opened_at,closed_at,validation_due,assessment_due,action_due,next_due,overdue,notices')
        .lt('opened_at', toUtc)
        .or(`closed_at.is.null,closed_at.gte."${fromUtc}"`)
        .order('opened_at')
        .range(a, b),
    ),
    fetchAllPages<{ signal_id: string; step: SignalStep; comment: string | null; person_id: string; created_at: string; due: string | null }>(
      async (a, b) =>
        await supabase
          .from('signal_event')
          .select('signal_id,step,comment,person_id,created_at,due')
          .gte('created_at', fromUtc)
          .lt('created_at', toUtc)
          .order('created_at')
          .range(a, b),
    ),
    fetchAllPages<{ person_id: string | null; issue_id: string | null; kind: NotifKind; dry_run: boolean; sent_at: string; error: string | null; summary: string | null }>(
      async (a, b) =>
        await supabase
          .from('notification')
          .select('person_id,issue_id,kind,dry_run,sent_at,error,summary')
          .gte('sent_at', fromUtc)
          .lt('sent_at', toUtc)
          .order('sent_at')
          .range(a, b),
    ),
    fetchAllPages<{ table_name: string; row_pk: string | null; action: string; old_row: unknown; new_row: unknown; actor: string | null; at: string }>(
      async (a, b) =>
        await supabase
          .from('audit_log')
          .select('table_name,row_pk,action,old_row,new_row,actor,at')
          .gte('at', fromUtc)
          .lt('at', toUtc)
          .order('at')
          .range(a, b),
      1000,
      20000,
    ),
    fetchAllPages<{ checked_at: string; sampled: number; mismatched: number; missing: number }>(async (a, b) =>
      await supabase
        .from('archive_check')
        .select('checked_at,sampled,mismatched,missing')
        .gte('checked_at', fromUtc)
        .lt('checked_at', toUtc)
        .order('checked_at')
        .range(a, b),
    ),
    fetchAllPages<{ id: string; full_name: string; role: PersonRole; active: boolean; auth_user_id: string | null; created_at: string }>(
      async (a, b) => await supabase.from('person').select('id,full_name,role,active,auth_user_id,created_at').order('full_name').range(a, b),
    ),
    fetchAllPages<{ inn_en: string; atc_code: string | null; active: boolean; terms: { lang: string; term: string; kind: string; verified_at: string | null }[] }>(
      async (a, b) =>
        await supabase.from('ingredient').select('inn_en,atc_code,active,terms:ingredient_term(lang,term,kind,verified_at)').order('inn_en').range(a, b),
    ),
  ]);

  // Audit rows name the auth user; people, the person id. Both resolve to a name.
  const byAuth = new Map(people.filter((p) => p.auth_user_id).map((p) => [p.auth_user_id as string, p.full_name] as const));
  const names = await personNames([
    ...reviews.map((r) => r.person_id),
    ...signalEvents.map((e) => e.person_id),
    ...alerts.map((n) => n.person_id),
  ]);
  const nameOf = (id: string | null) => (id ? (names.get(id) ?? 'A person no longer listed') : 'PHAROS (automatic)');
  const signalRef = new Map(signals.map((s) => [s.id, s.ref] as const));
  for (const e of signalEvents) {
    if (!signalRef.has(e.signal_id)) {
      const s = unwrap<{ ref: string } | null>(await supabase.from('signal').select('ref').eq('id', e.signal_id).maybeSingle());
      signalRef.set(e.signal_id, s?.ref ?? '—');
    }
  }

  progress('Writing the workbook');
  const Excel = await loadExcel();
  const wb = new Excel.Workbook();
  wb.creator = 'PHAROS';
  wb.created = new Date();

  // ── 1. About ───────────────────────────────────────────────────────────────────────────────────────
  const decidedHours = issues
    .map((i) => hoursBetween(i.created_at, firstDecision.get(i.id) ?? null))
    .filter((h): h is number => h !== null);
  const enabled = sources.filter((s) => s.enabled);
  const regulators = new Set(enabled.map((s) => s.regulator?.name).filter(Boolean));
  const covByDay = new Map<string, number>();
  for (const c of coverage) if (c.ok_runs > 0) covByDay.set(c.day, (covByDay.get(c.day) ?? 0) + 1);
  const daysScreened = days.filter((d) => (covByDay.get(d) ?? 0) > 0).length;

  const about = wb.addWorksheet('About', { properties: { tabColor: { argb: INK } } });
  about.columns = [
    { key: 'a', width: 34 },
    { key: 'b', width: 110 },
  ];
  const title = about.addRow({ a: 'PHAROS inspection pack' });
  title.font = { bold: true, size: 16, color: { argb: INK } };
  about.addRow({ a: 'Pharmaceutical Alerts & Regulatory Observation System, Sato Pharma pharmacovigilance' });
  about.addRow({});
  const facts: [string, string][] = [
    ['Period', `${formatDate(from)} to ${formatDate(to)} (Cairo local days, ${days.length} days)`],
    ['Prepared', `${formatDateTime(new Date().toISOString())} Cairo, by ${by}`],
    ['Sources screened', `${enabled.length} sources from ${regulators.size} regulators and reference databases`],
    ['Days with at least one successful read', `${daysScreened} of ${days.length}`],
    ['Notices found in the period', String(issues.length)],
    ['…with a decision recorded', String(issues.filter((i) => firstDecision.has(i.id)).length)],
    ['…still New today', String(issues.filter((i) => i.status === 'new').length)],
    ['Median time to the first decision', decidedHours.length ? `${median(decidedHours)} hours` : '—'],
    ['Decisions recorded in the period', String(reviews.length)],
    ['Signals open at any time in the period', String(signals.length)],
    ['Archive integrity checks in the period', `${checks.length}, ${checks.filter((c) => c.mismatched + c.missing > 0).length} with a failure`],
  ];
  for (const [a, b] of facts) {
    const r = about.addRow({ a, b });
    r.getCell('a').font = { bold: true, color: { argb: INK } };
    r.border = { bottom: { style: 'thin', color: { argb: LINE } } };
  }
  about.addRow({});
  const how = about.addRow({ a: 'How PHAROS works' });
  how.font = { bold: true, size: 13, color: { argb: INK } };
  const description: [string, string][] = [
    ['What it watches', 'The active ingredients on the watchlist (sheet "Watchlist"), each with its names in the languages of the regulators that publish about it.'],
    ['Where it reads', 'The safety channels, DHPC lists, recall lists and product-information databases of the reference regulators (sheet "Sources"): web pages, feeds, public data files, APIs and newsletters received by the PV mailbox. Each source is read on its own schedule, from every 4 hours to monthly.'],
    ['How it finds a notice', 'Every notice and its attached PDFs are read in their own language and matched against the watchlist terms, never translated. A match keeps the exact words and where they were found.'],
    ['The archive', 'Every original is stored once under its SHA-256 fingerprint in a storage bucket whose lock forbids overwriting or deleting. Every week 50 random originals are fingerprinted again and compared (sheet "Archive checks").'],
    ['The review', 'Each notice is New until a reviewer records Reviewed, Relevant or Not relevant. Not relevant needs a reason. Decisions are kept in an append-only history: the database stamps the person and the time, and a decision cannot be edited or deleted, only followed by another (sheet "Decisions").'],
    ['Signals', 'A Relevant notice opens a signal, which is validated, prioritised, assessed and closed with its outcome and any action. Every step is kept in an append-only history with the person and the time (sheets "Signals" and "Signal steps").'],
    ['Alerts', 'People who subscribe receive a Telegram message for each new notice on their ingredients, and a daily digest of class-wide notices (sheet "Alerts").'],
    ['Access', 'By invitation only. Readers see everything; reviewers also record decisions and signal steps; administrators also manage the watchlist, sources and people (sheet "People"). Row-level security in the database enforces this for every request.'],
    ['Audit trail', 'Every change to the watchlist, sources, people, settings, notice links and signals is recorded with the old and new values, who made it and when (sheet "Audit trail").'],
    ['Sign-off', 'A monthly report is approved by an administrator, and a closed signal reviewed or approved by a reviewer or administrator, by entering their password again. The signature records the name, role, meaning, time and the SHA-256 of the record as signed, and can never be changed or removed (sheet "Sign-offs").'],
    ['Coverage', 'Sheet "Coverage" shows, for each source and each day, the reads that succeeded (✓ and their number) or only failed (✗). A blank day is a day the source was not due, or the run that would have read it did not start; weekly and monthly sources are blank on most days.'],
    ['Backups and changes', 'The database is backed up every night, encrypted, to separate storage. Every change to PHAROS goes through a reviewed pull request with automated checks before it reaches the live system.'],
  ];
  for (const [a, b] of description) {
    const r = about.addRow({ a, b });
    r.getCell('a').font = { bold: true, color: { argb: INK } };
    r.alignment = { vertical: 'top', wrapText: true };
    r.border = { bottom: { style: 'thin', color: { argb: LINE } } };
  }
  about.addRow({});
  about.addRow({ a: 'Times', b: 'All times are Cairo local time. Titles are the regulators’ originals, exactly as published.' });

  // ── 2. Coverage ─────────────────────────────────────────────────────────────────────────────────────
  const cov = wb.addWorksheet('Coverage', { views: [{ state: 'frozen', xSplit: 4, ySplit: 1 }] });
  cov.columns = [
    { header: 'Country', key: 'country', width: 16 },
    { header: 'Regulator', key: 'regulator', width: 30 },
    { header: 'Source', key: 'source', width: 22 },
    { header: 'Schedule', key: 'schedule', width: 13 },
    ...days.map((d) => ({ header: d.slice(5).replace('-', '/'), key: d, width: 5.5 })),
  ];
  const covHead = cov.getRow(1);
  covHead.font = { bold: true, color: { argb: INK }, size: 9 };
  covHead.border = { bottom: { style: 'thin', color: { argb: INK } } };
  const cell = new Map(coverage.map((c) => [`${c.source_id}|${c.day}`, c] as const));
  const covSources = sources
    .filter((s) => s.enabled || coverage.some((c) => c.source_id === s.id))
    .sort((a, b) => (a.regulator?.country_name ?? '').localeCompare(b.regulator?.country_name ?? '') || a.id.localeCompare(b.id));
  for (const s of covSources) {
    const row = cov.addRow({
      country: s.regulator?.country_name ?? '',
      regulator: s.regulator?.name ?? '',
      source: s.id,
      schedule: SCHEDULE_LABEL[s.schedule] ?? s.schedule,
    });
    const created = s.created_at.slice(0, 10);
    days.forEach((d, i) => {
      const c = cell.get(`${s.id}|${d}`);
      const x = row.getCell(5 + i);
      x.alignment = { horizontal: 'center' };
      x.font = { size: 9 };
      if (c && c.ok_runs > 0) {
        x.value = `✓${c.ok_runs > 1 ? c.ok_runs : ''}`;
        x.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: OK_FILL } };
        x.font = { size: 9, color: { argb: OK_TEXT } };
        if (c.failed_runs > 0) x.note = `${c.ok_runs} read, ${c.failed_runs} failed; ${c.items_seen} items seen, ${c.items_matched} matched`;
      } else if (c && c.failed_runs > 0) {
        x.value = '✗';
        x.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: FAIL_FILL } };
        x.font = { size: 9, bold: true, color: { argb: FAIL_TEXT } };
      } else if (d < created) {
        x.value = '·';
        x.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: NONE_FILL } };
      }
    });
    row.border = { bottom: { style: 'hair', color: { argb: LINE } } };
  }
  cov.addRow({});
  cov.addRow({ country: '✓ read successfully (the number of reads when more than one) · ✗ every read that day failed · · not yet in PHAROS · blank: not due, or no run' });

  // ── 3. Screening log ────────────────────────────────────────────────────────────────────────────────
  const log = wb.addWorksheet('Screening log');
  headRow(log, [
    { header: 'Country', key: 'country', width: 16 },
    { header: 'Regulator', key: 'regulator', width: 34 },
    { header: 'Source', key: 'source', width: 24 },
    { header: 'Kind', key: 'kind', width: 22 },
    { header: 'Read as', key: 'channel', width: 24 },
    { header: 'Reads', key: 'runs', width: 9 },
    { header: 'Succeeded', key: 'ok', width: 11 },
    { header: 'Failed', key: 'failed', width: 9 },
    { header: 'Days read', key: 'days', width: 10 },
    { header: 'Items seen', key: 'seen', width: 11 },
    { header: 'Matched', key: 'matched', width: 10 },
    { header: 'Health today', key: 'health', width: 20 },
  ]);
  for (const s of covSources) {
    const mine = coverage.filter((c) => c.source_id === s.id);
    log.addRow({
      country: s.regulator?.country_name ?? '',
      regulator: s.regulator?.name ?? '',
      source: s.id,
      kind: KIND_LABEL[s.kind] ?? s.kind,
      channel: CHANNEL_LABEL[s.channel] ?? s.channel,
      runs: mine.reduce((n, c) => n + c.runs, 0),
      ok: mine.reduce((n, c) => n + c.ok_runs, 0),
      failed: mine.reduce((n, c) => n + c.failed_runs, 0),
      days: mine.filter((c) => c.ok_runs > 0).length,
      seen: mine.reduce((n, c) => n + c.items_seen, 0),
      matched: mine.reduce((n, c) => n + c.items_matched, 0),
      health: (HEALTH_LABEL[s.health] ?? HEALTH_LABEL.unknown).label,
    });
  }
  ruled(log);

  // ── 4. Notices ──────────────────────────────────────────────────────────────────────────────────────
  const notices = wb.addWorksheet('Notices');
  headRow(notices, [
    { header: 'Found by PHAROS', key: 'found', width: 18 },
    { header: 'Published', key: 'published', width: 13 },
    { header: 'Country', key: 'country', width: 16 },
    { header: 'Regulator', key: 'regulator', width: 30 },
    { header: 'Ingredient', key: 'ingredient', width: 18 },
    { header: 'Notice (original title)', key: 'title', width: 70 },
    { header: 'Type', key: 'type', width: 16 },
    { header: 'Status today', key: 'status', width: 14 },
    { header: 'First decision', key: 'decided', width: 18 },
    { header: 'Hours to first decision', key: 'hours', width: 12 },
    { header: 'Link', key: 'link', width: 40 },
  ]);
  for (const i of issues) {
    const v = issueView.get(i.id);
    const first = firstDecision.get(i.id) ?? null;
    notices.addRow({
      found: formatDateTime(i.created_at),
      published: formatDate(i.first_date),
      country: v?.anchor_country ?? '',
      regulator: v?.anchor_regulator ?? '',
      ingredient: i.class_only ? 'Class-wide' : (v?.ingredients ?? []).join(', '),
      title: i.title,
      type: DOC_TYPE_LABEL[i.doc_type] ?? i.doc_type,
      status: STATUS_LABEL[i.status] ?? i.status,
      decided: first ? formatDateTime(first) : 'Not yet',
      hours: hoursBetween(i.created_at, first),
      link: v?.link ?? '',
    });
  }
  ruled(notices);

  // ── 5. Decisions ────────────────────────────────────────────────────────────────────────────────────
  const decisions = wb.addWorksheet('Decisions');
  headRow(decisions, [
    { header: 'When', key: 'when', width: 18 },
    { header: 'Who', key: 'who', width: 22 },
    { header: 'Notice', key: 'notice', width: 60 },
    { header: 'From', key: 'from', width: 13 },
    { header: 'To', key: 'to', width: 13 },
    { header: 'Comment', key: 'comment', width: 60 },
  ]);
  for (const r of reviews) {
    decisions.addRow({
      when: formatDateTime(r.created_at),
      who: nameOf(r.person_id),
      notice: issueView.get(r.issue_id)?.title ?? '',
      from: STATUS_LABEL[r.from_status],
      to: STATUS_LABEL[r.to_status],
      comment: r.comment ?? '',
    });
  }
  ruled(decisions);

  // ── 6. Signals and their steps ──────────────────────────────────────────────────────────────────────
  const sig = wb.addWorksheet('Signals');
  headRow(sig, [
    { header: 'Signal', key: 'ref', width: 14 },
    { header: 'Title', key: 'title', width: 44 },
    { header: 'Ingredient', key: 'ingredient', width: 18 },
    { header: 'Stage today', key: 'stage', width: 13 },
    { header: 'Priority', key: 'priority', width: 10 },
    { header: 'Outcome', key: 'outcome', width: 22 },
    { header: 'Owner', key: 'owner', width: 20 },
    { header: 'Opened', key: 'opened', width: 18 },
    { header: 'Validation due', key: 'vdue', width: 14 },
    { header: 'Assessment due', key: 'adue', width: 14 },
    { header: 'Action due', key: 'xdue', width: 14 },
    { header: 'Closed', key: 'closed', width: 18 },
    { header: 'Overdue today', key: 'overdue', width: 11 },
    { header: 'Notices', key: 'notices', width: 9 },
  ]);
  for (const s of signals) {
    sig.addRow({
      ref: s.ref,
      title: s.title,
      ingredient: s.ingredient ?? '',
      stage: SIGNAL_STAGE_LABEL[s.stage],
      priority: s.priority ? SIGNAL_PRIORITY_LABEL[s.priority] : '',
      outcome: s.outcome ? SIGNAL_OUTCOME_LABEL[s.outcome].label : '',
      owner: s.owner ?? '',
      opened: formatDateTime(s.opened_at),
      vdue: formatDate(s.validation_due),
      adue: formatDate(s.assessment_due),
      xdue: formatDate(s.action_due),
      closed: s.closed_at ? formatDateTime(s.closed_at) : '',
      overdue: s.overdue ? 'Yes' : '',
      notices: Number(s.notices),
    });
  }
  ruled(sig);
  const steps = wb.addWorksheet('Signal steps');
  headRow(steps, [
    { header: 'When', key: 'when', width: 18 },
    { header: 'Signal', key: 'ref', width: 14 },
    { header: 'Step', key: 'step', width: 26 },
    { header: 'Who', key: 'who', width: 22 },
    { header: 'Due', key: 'due', width: 13 },
    { header: 'Comment', key: 'comment', width: 70 },
  ]);
  for (const e of signalEvents) {
    steps.addRow({
      when: formatDateTime(e.created_at),
      ref: signalRef.get(e.signal_id) ?? '—',
      step: SIGNAL_STEP_LABEL[e.step],
      who: nameOf(e.person_id),
      due: e.due ? formatDate(e.due) : '',
      comment: e.comment ?? '',
    });
  }
  ruled(steps);

  // ── 7. Alerts ───────────────────────────────────────────────────────────────────────────────────────
  const al = wb.addWorksheet('Alerts');
  headRow(al, [
    { header: 'When', key: 'when', width: 18 },
    { header: 'To', key: 'to', width: 22 },
    { header: 'Kind', key: 'kind', width: 18 },
    { header: 'Result', key: 'result', width: 26 },
    { header: 'About', key: 'about', width: 70 },
  ]);
  for (const n of alerts) {
    al.addRow({
      when: formatDateTime(n.sent_at),
      to: n.person_id ? nameOf(n.person_id) : '',
      kind: NOTIF_KIND_LABEL[n.kind] ?? n.kind,
      result: n.dry_run ? 'Prepared, not sent (test mode)' : n.error ? `Failed: ${n.error}` : 'Sent',
      about: n.summary ?? (n.issue_id ? (issueView.get(n.issue_id)?.title ?? '') : ''),
    });
  }
  ruled(al);

  // ── 8. Audit trail ──────────────────────────────────────────────────────────────────────────────────
  const au = wb.addWorksheet('Audit trail');
  headRow(au, [
    { header: 'When', key: 'when', width: 18 },
    { header: 'Who', key: 'who', width: 22 },
    { header: 'Table', key: 'table', width: 18 },
    { header: 'Record', key: 'pk', width: 38 },
    { header: 'Change', key: 'change', width: 60 },
  ]);
  for (const a of audit) {
    au.addRow({
      when: formatDateTime(a.at),
      who: a.actor ? (byAuth.get(a.actor) ?? 'A person no longer listed') : 'PHAROS (automatic)',
      table: a.table_name,
      pk: a.row_pk ?? '',
      change: auditChange(a.action, a.old_row, a.new_row),
    });
  }
  if (audit.length >= 20000) au.addRow({ when: 'The first 20,000 changes of the period are listed. Choose a shorter period for the rest.' });
  ruled(au);

  // ── 8b. Sign-offs ───────────────────────────────────────────────────────────────────────────────────
  const signOffs = await fetchAllPages<{ record_kind: string; record_id: string; record_sha256: string; meaning: string; signed_name: string; signed_role: PersonRole; comment: string | null; signed_at: string }>(
    async (a, b) =>
      await supabase
        .from('sign_off')
        .select('record_kind,record_id,record_sha256,meaning,signed_name,signed_role,comment,signed_at')
        .gte('signed_at', fromUtc)
        .lt('signed_at', toUtc)
        .order('signed_at')
        .range(a, b),
  );
  const sg = wb.addWorksheet('Sign-offs');
  headRow(sg, [
    { header: 'Signed', key: 'when', width: 18 },
    { header: 'Name', key: 'name', width: 24 },
    { header: 'Role', key: 'role', width: 14 },
    { header: 'Meaning', key: 'meaning', width: 12 },
    { header: 'Record', key: 'kind', width: 16 },
    { header: 'Record id', key: 'id', width: 38 },
    { header: 'SHA-256 of the record as signed', key: 'sha', width: 66 },
    { header: 'Comment', key: 'comment', width: 40 },
  ]);
  for (const s of signOffs) {
    sg.addRow({
      when: formatDateTime(s.signed_at),
      name: s.signed_name,
      role: ROLE_LABEL[s.signed_role] ?? s.signed_role,
      meaning: s.meaning === 'approved' ? 'Approved' : 'Reviewed',
      kind: s.record_kind === 'monthly_report' ? 'Monthly report' : 'Signal',
      id: s.record_id,
      sha: s.record_sha256,
      comment: s.comment ?? '',
    });
  }
  ruled(sg);

  // ── 9. Archive checks ───────────────────────────────────────────────────────────────────────────────
  const ac = wb.addWorksheet('Archive checks');
  headRow(ac, [
    { header: 'When', key: 'when', width: 18 },
    { header: 'Originals re-fingerprinted', key: 'sampled', width: 16 },
    { header: 'Different', key: 'mismatched', width: 11 },
    { header: 'Missing', key: 'missing', width: 10 },
    { header: 'Result', key: 'result', width: 30 },
  ]);
  for (const c of checks) {
    ac.addRow({
      when: formatDateTime(c.checked_at),
      sampled: c.sampled,
      mismatched: c.mismatched,
      missing: c.missing,
      result: c.mismatched + c.missing === 0 ? 'Every original matched' : 'Failure: see the operations log',
    });
  }
  ruled(ac);

  // ── 10. Sources, watchlist and people ───────────────────────────────────────────────────────────────
  const so = wb.addWorksheet('Sources');
  headRow(so, [
    { header: 'Country', key: 'country', width: 16 },
    { header: 'Regulator', key: 'regulator', width: 34 },
    { header: 'Source', key: 'source', width: 24 },
    { header: 'Kind', key: 'kind', width: 22 },
    { header: 'Read as', key: 'channel', width: 24 },
    { header: 'Schedule', key: 'schedule', width: 14 },
    { header: 'Switched on', key: 'enabled', width: 11 },
    { header: 'Last successful read', key: 'last', width: 18 },
    { header: 'Address', key: 'url', width: 60 },
  ]);
  for (const s of sources) {
    so.addRow({
      country: s.regulator?.country_name ?? '',
      regulator: s.regulator?.name ?? '',
      source: s.id,
      kind: KIND_LABEL[s.kind] ?? s.kind,
      channel: CHANNEL_LABEL[s.channel] ?? s.channel,
      schedule: SCHEDULE_LABEL[s.schedule] ?? s.schedule,
      enabled: s.enabled ? 'Yes' : 'No',
      last: s.last_ok_at ? formatDateTime(s.last_ok_at) : '—',
      url: s.url,
    });
  }
  ruled(so);

  const wl = wb.addWorksheet('Watchlist');
  headRow(wl, [
    { header: 'Ingredient', key: 'inn', width: 20 },
    { header: 'ATC code', key: 'atc', width: 11 },
    { header: 'Watched', key: 'active', width: 9 },
    { header: 'Language', key: 'lang', width: 10 },
    { header: 'Term searched', key: 'term', width: 30 },
    { header: 'Kind of term', key: 'kind', width: 14 },
    { header: 'Checked by a person', key: 'verified', width: 18 },
  ]);
  for (const ing of watch) {
    for (const t of [...(ing.terms ?? [])].sort((a, b) => a.lang.localeCompare(b.lang) || a.term.localeCompare(b.term))) {
      wl.addRow({
        inn: ing.inn_en,
        atc: ing.atc_code ?? '',
        active: ing.active ? 'Yes' : 'No',
        lang: t.lang,
        term: t.term,
        kind: t.kind,
        verified: t.verified_at ? formatDate(t.verified_at) : '',
      });
    }
  }
  ruled(wl);

  const pe = wb.addWorksheet('People');
  headRow(pe, [
    { header: 'Name', key: 'name', width: 26 },
    { header: 'Role', key: 'role', width: 16 },
    { header: 'Account', key: 'active', width: 12 },
    { header: 'Invited', key: 'created', width: 14 },
  ]);
  for (const p of people) {
    pe.addRow({
      name: p.full_name,
      role: ROLE_LABEL[p.role],
      active: p.active ? 'Active' : 'Switched off',
      created: formatCairoDate(p.created_at),
    });
  }
  ruled(pe);

  const buf = await wb.xlsx.writeBuffer();
  downloadBlob(
    new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    `PHAROS-inspection-pack-${from}-to-${to}.xlsx`,
  );
  progress(`Saved on ${formatDate(cairoToday())}`);
}
