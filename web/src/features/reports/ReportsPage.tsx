import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { downloadArchived, errorMessage, unwrap } from '../../lib/api';
import { cairoToday, formatDateTime, formatMonth, formatNumber, isScreenedMonth } from '../../lib/format';
import { CHANNEL_LABEL, KIND_LABEL } from '../../lib/labels';
import type { MonthlyReport } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Country } from '../../ui/Flag';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { PageHead, SectionHead } from '../../ui/Text';
import { Stat, StatRow } from '../../ui/Stat';
import { useSources } from '../sources/queries';
import { SignOff } from '../signoff/SignOff';
import { FileHash } from './FileHash';
import { Packs } from './Packs';
import {
  type DailyReport,
  type WeeklyReport,
  dailyFileName,
  dayLabel,
  lastCompleteWeek,
  newestWeekFirst,
  weekDays,
  weekLabel,
  weekOptions,
  weeklyFileName,
} from './weeks';
import '../../styles/reports-weekly.css';

/** "PHAROS-screening-2026-10.xlsx": the month an old monthly report covers. */
function monthlyFileName(month: string, ext: 'xlsx' | 'pdf'): string {
  return `PHAROS-screening-${month.slice(0, 7)}.${ext}`;
}

type Save = (key: string, filename: string) => Promise<void>;

function useSave(): { error: string | null; save: Save } {
  const [error, setError] = useState<string | null>(null);
  async function save(key: string, filename: string) {
    setError(null);
    try {
      await downloadArchived(key, filename);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return { error, save };
}

/** The two files of one report: [archive key, the name it is saved under]. */
function Files({ name, pdf, xlsx, save }: { name: string; pdf: [string, string]; xlsx: [string, string]; save: Save }) {
  return (
    <div className="button-row report-files">
      <Button size="sm" onClick={() => void save(pdf[0], pdf[1])} aria-label={`Download the ${name} report as PDF`}>
        PDF
      </Button>
      <Button size="sm" onClick={() => void save(xlsx[0], xlsx[1])} aria-label={`Download the ${name} report as Excel`}>
        Excel
      </Button>
    </div>
  );
}

/** The days shown at once; the earlier ones open below them. */
const RECENT_DAYS = 14;

function DayRows({ rows, save }: { rows: DailyReport[]; save: Save }) {
  return (
    <Table className="reports">
      <tbody>
        {rows.map((r) => {
          const name = dayLabel(r.day);
          return (
            <tr key={r.id} className="report-row">
              <td>
                <span className="report-month">{name}</span>
                <span className="cell-sub">
                  Made <span className="mono">{formatDateTime(r.made_at)}</span>
                </span>
              </td>
              <td className="num">
                <Files
                  name={name}
                  pdf={[r.pdf_r2_key, dailyFileName(r.day, 'pdf')]}
                  xlsx={[r.xlsx_r2_key, dailyFileName(r.day, 'xlsx')]}
                  save={save}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

/** The daily reports (0083): each Cairo day's outcome, made the next morning at 07:00. Not signed: the week is. */
function DailyReports() {
  const { error, save } = useSave();
  const reports = useQuery({
    queryKey: ['daily-reports'],
    queryFn: async () =>
      unwrap<DailyReport[] | null>(
        await supabase.from('daily_report').select('*').order('day', { ascending: false }),
      ) ?? [],
  });

  if (reports.isPending) return <Loading label="Reading the reports" />;
  if (reports.isError) return <ErrorNote error={reports.error} onRetry={() => void reports.refetch()} />;
  if (reports.data.length === 0) {
    return (
      <Empty title="No daily report yet.">
        <p>The report is made every morning at 07:00 Cairo time, for the day before.</p>
      </Empty>
    );
  }
  const recent = reports.data.slice(0, RECENT_DAYS);
  const earlier = reports.data.slice(RECENT_DAYS);
  return (
    <>
      {error ? <Notice tone="error">The file could not be downloaded: {error}</Notice> : null}
      <DayRows rows={recent} save={save} />
      {earlier.length > 0 ? (
        <details className="reports-monthly">
          <summary>
            <span className="reports-monthly-title">Earlier days</span>
            <span className="reports-monthly-sum">
              {earlier.length === 1 ? '1 report' : `${formatNumber(earlier.length)} reports`}
            </span>
          </summary>
          <DayRows rows={earlier} save={save} />
        </details>
      ) : null}
    </>
  );
}

function WeeklyReports() {
  const { error, save } = useSave();
  const reports = useQuery({
    queryKey: ['weekly-reports'],
    queryFn: async () =>
      newestWeekFirst(
        unwrap<WeeklyReport[] | null>(
          await supabase.from('weekly_report').select('*').order('week_start', { ascending: false }),
        ) ?? [],
      ),
  });

  if (reports.isPending) return <Loading label="Reading the reports" />;
  if (reports.isError) return <ErrorNote error={reports.error} onRetry={() => void reports.refetch()} />;
  if (reports.data.length === 0) {
    return (
      <Empty title="No weekly report yet.">
        <p>The report is made every Sunday at 05:00 Cairo time, for the week that has just ended.</p>
      </Empty>
    );
  }
  return (
    <>
      {error ? <Notice tone="error">The file could not be downloaded: {error}</Notice> : null}
      <ul className="weekly-list">
        {reports.data.map((r) => {
          const name = weekLabel(r.week_start);
          return (
            <li key={r.id} className="weekly-card">
              <div className="weekly-head">
                <span className="report-month">{name}</span>
                <span className="cell-sub">
                  Made <span className="mono">{formatDateTime(r.made_at)}</span>
                </span>
              </div>
              <div className="evidence-files">
                <div className="evidence-file">
                  <Button
                    className="evidence-download"
                    onClick={() => void save(r.pdf_r2_key, weeklyFileName(r.week_start, 'pdf'))}
                    aria-label={`Download the ${name} report as PDF`}
                  >
                    PDF
                  </Button>
                  <FileHash hash={r.pdf_sha256} what={`PDF of ${name}`} />
                </div>
                <div className="evidence-file">
                  <Button
                    className="evidence-download"
                    onClick={() => void save(r.xlsx_r2_key, weeklyFileName(r.week_start, 'xlsx'))}
                    aria-label={`Download the ${name} report as Excel`}
                  >
                    Excel
                  </Button>
                  <FileHash hash={r.xlsx_sha256} what={`Excel file of ${name}`} />
                </div>
              </div>
              <SignOff kind="weekly_report" id={r.id} name={name} />
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** The monthly reports made before the weekly report replaced them; shown only when there are any. */
function MonthlyReports() {
  const { error, save } = useSave();
  const reports = useQuery({
    queryKey: ['monthly-reports'],
    // A report for a month before PHAROS started would read as "screened, nothing found"; it is not offered.
    queryFn: async () =>
      (
        unwrap<MonthlyReport[] | null>(
          await supabase.from('monthly_report').select('*').order('month', { ascending: false }),
        ) ?? []
      ).filter((r) => isScreenedMonth(r.month)),
  });

  if (reports.isPending || reports.isError || reports.data.length === 0) return null;
  return (
    <details className="reports-monthly">
      <summary>
        <span className="reports-monthly-title">Monthly reports (until November 2026)</span>
        <span className="reports-monthly-sum">
          {reports.data.length === 1 ? '1 report' : `${formatNumber(reports.data.length)} reports`}
        </span>
      </summary>
      {error ? <Notice tone="error">The file could not be downloaded: {error}</Notice> : null}
      <Table className="reports">
        <tbody>
          {reports.data.map((r) => (
            <tr key={r.id} className="report-row">
              <td>
                <span className="report-month">{formatMonth(r.month)}</span>
                <span className="cell-sub">
                  Made <span className="mono">{formatDateTime(r.generated_at)}</span>
                </span>
              </td>
              <td className="num">
                <Files
                  name={formatMonth(r.month)}
                  pdf={[r.pdf_r2_key, monthlyFileName(r.month, 'pdf')]}
                  xlsx={[r.xlsx_r2_key, monthlyFileName(r.month, 'xlsx')]}
                  save={save}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </details>
  );
}

interface ScreeningRow {
  source_id: string;
  regulator: string;
  country: string;
  country_code: string | null;
  enabled: boolean;
  runs: number;
  ok_runs: number;
  failed_runs: number;
  items_seen: number;
  items_new: number;
  items_matched: number;
  last_run: string | null;
}

function ScreeningLog() {
  const today = cairoToday();
  const options = useMemo(() => weekOptions(today), [today]);
  const [week, setWeek] = useState(() => lastCompleteWeek(today));
  const sources = useSources();
  // Counted in the database for the Cairo days of the week, both included (bigint counts arrive as numbers or
  // strings). Every read counts, whatever started it.
  const log = useQuery({
    queryKey: ['screening-log', week],
    queryFn: async () => {
      const { from, to } = weekDays(week);
      return (
        unwrap<ScreeningRow[] | null>(await supabase.rpc('screening_log', { p_from: from, p_to: to })) ?? []
      ).map((r) => ({
        ...r,
        runs: Number(r.runs),
        ok_runs: Number(r.ok_runs),
        failed_runs: Number(r.failed_runs),
        items_seen: Number(r.items_seen),
        items_new: Number(r.items_new),
        items_matched: Number(r.items_matched),
      }));
    },
  });
  const byId = useMemo(() => new Map((sources.data ?? []).map((s) => [s.id, s] as const)), [sources.data]);

  const sum = useMemo(() => {
    const t = { runs: 0, failed: 0, seen: 0, fresh: 0, matched: 0 };
    for (const r of log.data ?? []) {
      t.runs += r.runs;
      t.failed += r.failed_runs;
      t.seen += r.items_seen;
      t.fresh += r.items_new;
      t.matched += r.items_matched;
    }
    return t;
  }, [log.data]);

  return (
    <>
      <div className="inline-form">
        <Field label="Week">
          <Select value={week} options={options} onChange={(e) => e.target.value && setWeek(e.target.value)} />
        </Field>
        <p className="small muted">
          Every check of every source from Sunday to Saturday (Cairo time), including checks that found nothing.
        </p>
      </div>
      {log.isPending ? (
        <Loading label="Counting the checks" />
      ) : log.isError ? (
        <ErrorNote error={log.error} onRetry={() => void log.refetch()} />
      ) : log.data.length === 0 ? (
        <Empty title="No sources are listed yet." />
      ) : (
        <>
          <StatRow label={`Screening, ${weekLabel(week)}`}>
            <Stat value={sum.runs} label="Checks" />
            <Stat value={sum.failed} label="Failed" tone={sum.failed ? 'danger' : 'quiet'} />
            <Stat value={sum.seen} label="Items read" />
            <Stat value={sum.fresh} label="New" tone="new" />
            <Stat value={sum.matched} label="Matched" tone="warning" />
          </StatRow>
          <Table className="screening">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col" className="num">
                  Checks
                </th>
                <th scope="col" className="num">
                  Failed
                </th>
                <th scope="col" className="num">
                  Items read
                </th>
                <th scope="col" className="num">
                  New
                </th>
                <th scope="col" className="num">
                  Matched
                </th>
                <th scope="col">Last check</th>
              </tr>
            </thead>
            <tbody>
              {log.data.map((r) => {
                const s = byId.get(r.source_id);
                const off = !r.enabled;
                return (
                  <tr key={r.source_id} className={off ? 'is-off' : undefined}>
                    <td className="col-source">
                      <span className="cell-line">
                        <span className="source-name">{r.regulator}</span>
                        <Country name={r.country} code={r.country_code ?? s?.regulator?.country_code ?? null} />
                      </span>
                      <span className="cell-sub">
                        {s ? `${KIND_LABEL[s.kind]} · ${CHANNEL_LABEL[s.channel]}` : '—'}
                        {off ? ' · switched off' : null}
                      </span>
                    </td>
                    {r.runs > 0 ? (
                      <>
                        <td className="num mono" data-label="Checks">
                          {formatNumber(r.runs)}
                        </td>
                        <td className={r.failed_runs ? 'num mono danger' : 'num mono'} data-label="Failed">
                          {formatNumber(r.failed_runs)}
                        </td>
                        <td className="num mono" data-label="Items read">
                          {formatNumber(r.items_seen)}
                        </td>
                        <td className="num mono" data-label="New">
                          {formatNumber(r.items_new)}
                        </td>
                        <td className={r.items_matched ? 'num mono is-hit' : 'num mono'} data-label="Matched">
                          {formatNumber(r.items_matched)}
                        </td>
                        <td className="small mono col-last" data-label="Last check">
                          {formatDateTime(r.last_run)}
                        </td>
                      </>
                    ) : (
                      <td colSpan={6} className={off ? 'muted small col-none' : 'accent-text small col-none'}>
                        No check recorded this week
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">All sources</th>
                <td className="num mono strong" data-label="Checks">
                  {formatNumber(sum.runs)}
                </td>
                <td className="num mono strong" data-label="Failed">
                  {formatNumber(sum.failed)}
                </td>
                <td className="num mono strong" data-label="Items read">
                  {formatNumber(sum.seen)}
                </td>
                <td className="num mono strong" data-label="New">
                  {formatNumber(sum.fresh)}
                </td>
                <td className="num mono strong" data-label="Matched">
                  {formatNumber(sum.matched)}
                </td>
                <td className="col-last" />
              </tr>
            </tfoot>
          </Table>
        </>
      )}
    </>
  );
}

export function ReportsPage() {
  return (
    <div className="page">
      <PageHead
        eyebrow="Evidence"
        title="Reports"
        lede="The daily report shows each day's outcome. The weekly report is the final one: it is signed and kept for the inspection. Below them, the PSUR and inspection packs made on request, and the screening log."
      />
      <section className="section">
        <SectionHead index="01" title="Daily reports" aside="Each day's outcome, made at 07:00 for the day before" />
        <DailyReports />
      </section>
      <section className="section">
        <SectionHead index="02" title="Weekly reports" aside="The final report: signed and kept for the inspection" />
        <WeeklyReports />
        <MonthlyReports />
      </section>
      <section className="section">
        <SectionHead index="03" title="Packs" />
        <Packs />
      </section>
      <section className="section">
        <SectionHead index="04" title="Screening log" />
        <ScreeningLog />
      </section>
    </div>
  );
}
