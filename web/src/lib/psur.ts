import { supabase } from './supabase';
import { fetchAllPages, unwrap } from './api';
import { downloadBlob } from './download';
import { cairoMidnightUtc, formatCairoDate, formatDate } from './format';
import { DOC_TYPE_LABEL, SIGNAL_OUTCOME_LABEL, SIGNAL_STAGE_LABEL, STATUS_LABEL } from './labels';
import type { DocType, IssueStatus, SignalRow, SourceKind } from './types';

/** The first day PHAROS screened; nothing before it comes from PHAROS's own records. */
export const FIRST_DAY = '2026-11-05';

export interface EurdEntry {
  eurd_id: number;
  ingredient_id: string;
  substance: string;
  combination: boolean;
  eurd: string | null;
  frequency: string | null;
  dlp: string | null;
  submission_date: string | null;
  next_dlp: string | null;
  next_submission_date: string | null;
  generics_psur_required: boolean | null;
  procedure: string | null;
  next_procedure: string | null;
  lead_ms: string | null;
  notes: string | null;
  list_version: string;
  list_date: string | null;
}

export interface PsurIssue {
  id: string;
  first_date: string | null;
  doc_type: DocType;
  title: string;
  status: IssueStatus;
  class_only: boolean;
  link: string | null;
  anchor_country: string | null;
  anchor_regulator: string | null;
  countries: string[] | null;
  lang: string | null;
}

export interface PsurLabelChange {
  id: string;
  sections: string[];
  created_at: string;
  issue_id: string | null;
  spc_product: { product_name: string; country_code: string; mah: string | null } | null;
}

export interface ScreeningRow {
  source_id: string;
  regulator: string;
  country: string;
  kind: SourceKind;
  runs: number;
  ok_runs: number;
  failed_runs: number;
  days_read: number;
  items_seen: number;
  items_matched: number;
  first_run: string | null;
  last_run: string | null;
}

export interface PsurData {
  actions: PsurIssue[];
  labels: PsurIssue[];
  labelChanges: PsurLabelChange[];
  literature: PsurIssue[];
  notRelevant: PsurIssue[];
  signals: SignalRow[];
  screening: ScreeningRow[];
}

/** "7 years" → 84, "6 months" → 6; null for anything else ("Not applicable", blank). */
export function frequencyMonths(frequency: string | null | undefined): number | null {
  const m = /^\s*(\d{1,2})\s*(year|month)s?\b/i.exec(frequency ?? '');
  if (!m) return null;
  return Number(m[1]) * (m[2].toLowerCase() === 'year' ? 12 : 1);
}

function addMonths(day: string, months: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, last));
  return target.toISOString().slice(0, 10);
}

function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d) + n * 86_400_000).toISOString().slice(0, 10);
}

/**
 * The reporting interval that ends at the EURD data lock point: the day after the previous DLP (one frequency
 * earlier) to the DLP itself. Null when the row has no DLP or no frequency in months or years.
 */
export function intervalFor(entry: Pick<EurdEntry, 'dlp' | 'frequency'>): { from: string; to: string } | null {
  const months = frequencyMonths(entry.frequency);
  if (!entry.dlp || !months) return null;
  return { from: addDays(addMonths(entry.dlp, -months), 1), to: entry.dlp };
}

/** The PBRER section a notice belongs to: §4 label changes, §11 literature, §3 every other action. */
export function pbrerSection(docType: DocType): 'actions' | 'labels' | 'literature' {
  if (docType === 'label_change') return 'labels';
  if (docType === 'literature') return 'literature';
  return 'actions';
}

/** Splits the notices of the interval into the PBRER sections; notices judged not relevant go apart. */
export function sortIssues(issues: PsurIssue[]): Pick<PsurData, 'actions' | 'labels' | 'literature' | 'notRelevant'> {
  const out = { actions: [] as PsurIssue[], labels: [] as PsurIssue[], literature: [] as PsurIssue[], notRelevant: [] as PsurIssue[] };
  for (const i of issues) {
    if (i.status === 'not_relevant') out.notRelevant.push(i);
    else out[pbrerSection(i.doc_type)].push(i);
  }
  return out;
}

/** A signal belongs to the interval when it was open on any day of it. */
export function signalInInterval(s: Pick<SignalRow, 'opened_at' | 'closed_at'>, from: string, to: string): boolean {
  const opened = formatCairoDay(s.opened_at);
  const closed = s.closed_at ? formatCairoDay(s.closed_at) : null;
  return opened <= to && (closed === null || closed >= from);
}

function formatCairoDay(ts: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Cairo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    new Date(ts),
  );
}

function utcBounds(from: string, to: string): { start: string; end: string } {
  const [fy, fm, fd] = from.split('-').map(Number);
  const [ty, tm, td] = addDays(to, 1).split('-').map(Number);
  return { start: cairoMidnightUtc(fy, fm, fd).toISOString(), end: cairoMidnightUtc(ty, tm, td).toISOString() };
}

/** Reads everything the PSUR sections need for one ingredient and interval. */
export async function loadPsurData(ingredientId: string, inn: string, from: string, to: string): Promise<PsurData> {
  const { start, end } = utcBounds(from, to);
  const [issues, labelChanges, signals, screening] = await Promise.all([
    fetchAllPages<PsurIssue>((a, b) =>
      supabase
        .from('v_issue_table')
        .select('id,first_date,doc_type,title,status,class_only,link,anchor_country,anchor_regulator,countries,lang')
        .contains('ingredients', [inn])
        .gte('first_date', from)
        .lte('first_date', to)
        .order('first_date')
        .order('id')
        .range(a, b),
    ),
    fetchAllPages<PsurLabelChange>((a, b) =>
      supabase
        .from('spc_change')
        .select('id,sections,created_at,issue_id,spc_product:spc_product_id!inner(product_name,country_code,mah)')
        .eq('spc_product.ingredient_id', ingredientId)
        .gte('created_at', start)
        .lt('created_at', end)
        .order('created_at')
        .range(a, b),
    ),
    fetchAllPages<SignalRow>((a, b) =>
      supabase.from('v_signal_table').select('*').eq('ingredient_id', ingredientId).order('opened_at').range(a, b),
    ),
    supabase.rpc('screening_summary', { p_from: from, p_to: to }),
  ]);
  return {
    ...sortIssues(issues),
    labelChanges,
    signals: signals.filter((s) => signalInInterval(s, from, to)),
    screening: unwrap<ScreeningRow[] | null>(screening) ?? [],
  };
}

type ExcelModule = typeof import('exceljs');
type Worksheet = import('exceljs').Worksheet;

async function loadExcel(): Promise<ExcelModule> {
  const mod = await import('exceljs');
  const withDefault = mod as unknown as { default?: ExcelModule };
  return withDefault.default ?? mod;
}

const INK = 'FF02224C';

function sheet(wb: import('exceljs').Workbook, name: string, columns: { header: string; key: string; width: number }[]): Worksheet {
  const ws = wb.addWorksheet(name);
  ws.columns = columns;
  const head = ws.getRow(1);
  head.font = { bold: true, color: { argb: INK } };
  head.border = { bottom: { style: 'thin', color: { argb: INK } } };
  head.alignment = { vertical: 'middle', wrapText: true };
  ws.views = [{ state: 'frozen', ySplit: 1 }];
  return ws;
}

const ISSUE_COLUMNS = [
  { header: 'Date', key: 'date', width: 12 },
  { header: 'Country', key: 'country', width: 16 },
  { header: 'Regulator', key: 'regulator', width: 30 },
  { header: 'Type', key: 'type', width: 16 },
  { header: 'Title (original language)', key: 'title', width: 70 },
  { header: 'Decision', key: 'status', width: 14 },
  { header: 'Link', key: 'link', width: 44 },
];

function issueRow(i: PsurIssue) {
  return {
    date: formatDate(i.first_date),
    country: i.anchor_country ?? i.countries?.[0] ?? '',
    regulator: i.anchor_regulator ?? '',
    type: DOC_TYPE_LABEL[i.doc_type] ?? i.doc_type,
    title: i.class_only ? `[Class-wide] ${i.title}` : i.title,
    status: STATUS_LABEL[i.status] ?? i.status,
    link: i.link ?? '',
  };
}

/** The PSUR input as one workbook: the EURD rows, each PBRER section and the screening annex. */
export async function downloadPsurWorkbook(inn: string, from: string, to: string, eurd: EurdEntry[], data: PsurData): Promise<void> {
  const Excel = await loadExcel();
  const wb = new Excel.Workbook();
  wb.creator = 'PHAROS';
  wb.created = new Date();

  const e = sheet(wb, 'EURD', [
    { header: 'Substance', key: 'substance', width: 36 },
    { header: 'Frequency', key: 'frequency', width: 12 },
    { header: 'DLP', key: 'dlp', width: 12 },
    { header: 'Submission', key: 'submission', width: 12 },
    { header: 'Next DLP', key: 'next', width: 12 },
    { header: 'Generics submit PSURs', key: 'generics', width: 12 },
    { header: 'Procedure', key: 'procedure', width: 24 },
    { header: 'Lead member state', key: 'lead', width: 16 },
    { header: 'List', key: 'list', width: 30 },
  ]);
  for (const r of eurd) {
    e.addRow({
      substance: r.substance,
      frequency: r.frequency ?? '',
      dlp: formatDate(r.dlp),
      submission: formatDate(r.submission_date),
      next: formatDate(r.next_dlp),
      generics: r.generics_psur_required === null ? '' : r.generics_psur_required ? 'Yes' : 'No',
      procedure: r.procedure ?? '',
      lead: r.lead_ms ?? '',
      list: `${r.list_version}${r.list_date ? `, ${formatDate(r.list_date)}` : ''}`,
    });
  }

  for (const [name, rows] of [
    ['§3 Actions', data.actions],
    ['§4 Label notices', data.labels],
    ['§11 Literature', data.literature],
    ['Not relevant', data.notRelevant],
  ] as const) {
    const ws = sheet(wb, name, ISSUE_COLUMNS);
    for (const i of rows) ws.addRow(issueRow(i));
  }

  const lc = sheet(wb, '§4 Label changes', [
    { header: 'Found', key: 'found', width: 12 },
    { header: 'Product', key: 'product', width: 40 },
    { header: 'Country', key: 'country', width: 10 },
    { header: 'Holder', key: 'mah', width: 30 },
    { header: 'Sections changed', key: 'sections', width: 24 },
  ]);
  for (const c of data.labelChanges) {
    lc.addRow({
      found: formatCairoDate(c.created_at),
      product: c.spc_product?.product_name ?? '',
      country: c.spc_product?.country_code ?? '',
      mah: c.spc_product?.mah ?? '',
      sections: c.sections.join(', '),
    });
  }

  const sg = sheet(wb, '§15-16 Signals', [
    { header: 'Signal', key: 'ref', width: 14 },
    { header: 'Title', key: 'title', width: 60 },
    { header: 'Opened', key: 'opened', width: 12 },
    { header: 'Stage', key: 'stage', width: 14 },
    { header: 'Outcome', key: 'outcome', width: 24 },
    { header: 'Closed', key: 'closed', width: 12 },
    { header: 'Notices', key: 'notices', width: 10 },
  ]);
  for (const s of data.signals) {
    sg.addRow({
      ref: s.ref,
      title: s.title,
      opened: formatCairoDate(s.opened_at),
      stage: SIGNAL_STAGE_LABEL[s.stage] ?? s.stage,
      outcome: s.outcome ? (SIGNAL_OUTCOME_LABEL[s.outcome]?.label ?? s.outcome) : '',
      closed: s.closed_at ? formatCairoDate(s.closed_at) : '',
      notices: s.notices,
    });
  }

  const sc = sheet(wb, 'Screening annex', [
    { header: 'Country', key: 'country', width: 18 },
    { header: 'Regulator', key: 'regulator', width: 34 },
    { header: 'Source', key: 'source', width: 26 },
    { header: 'Days read', key: 'days', width: 10 },
    { header: 'Reads', key: 'runs', width: 9 },
    { header: 'Failed reads', key: 'failed', width: 10 },
    { header: 'Items read', key: 'seen', width: 11 },
    { header: 'Matched', key: 'matched', width: 10 },
  ]);
  for (const r of data.screening) {
    sc.addRow({
      country: r.country,
      regulator: r.regulator,
      source: r.source_id,
      days: r.days_read,
      runs: r.runs,
      failed: r.failed_runs,
      seen: r.items_seen,
      matched: r.items_matched,
    });
  }

  const buf = await wb.xlsx.writeBuffer();
  const safe = inn.replace(/[^A-Za-z0-9-]+/g, '-');
  downloadBlob(
    new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
    `PHAROS-PSUR-${safe}-${from}-to-${to}.xlsx`,
  );
}
