import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, openArchived, unwrap } from '../../lib/api';
import { cairoThisMonth, formatDateTime, formatMonth, formatNumber, formatYearMonth } from '../../lib/format';
import { CHANNEL_LABEL, KIND_LABEL } from '../../lib/labels';
import type { MonthlyReport } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Country } from '../../ui/Flag';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { PageHead, SectionHead } from '../../ui/Text';
import { Stat, StatRow } from '../../ui/Stat';
import { useSources } from '../sources/queries';

function MonthlyReports() {
  const [openError, setOpenError] = useState<string | null>(null);
  const reports = useQuery({
    queryKey: ['monthly-reports'],
    queryFn: async () =>
      unwrap<MonthlyReport[] | null>(
        await supabase.from('monthly_report').select('*').order('month', { ascending: false }),
      ) ?? [],
  });

  async function open(key: string) {
    setOpenError(null);
    try {
      await openArchived(key);
    } catch (e) {
      setOpenError(errorMessage(e));
    }
  }

  if (reports.isPending) return <Loading label="Reading the reports" />;
  if (reports.isError) return <ErrorNote error={reports.error} onRetry={() => void reports.refetch()} />;
  if (reports.data.length === 0) {
    return (
      <Empty title="No monthly report yet.">
        <p>The first report is made on the 1st of next month, covering the month before.</p>
      </Empty>
    );
  }
  return (
    <>
      {openError ? <Notice tone="error">The file could not be opened: {openError}</Notice> : null}
      <Table className="reports">
        <thead>
          <tr>
            <th scope="col">Month</th>
            <th scope="col">Made</th>
            <th scope="col">Files</th>
          </tr>
        </thead>
        <tbody>
          {reports.data.map((r) => (
            <tr key={r.id}>
              <td className="strong">{formatMonth(r.month)}</td>
              <td className="small mono">{formatDateTime(r.generated_at)}</td>
              <td>
                <div className="button-row">
                  <Button size="sm" onClick={() => void open(r.xlsx_r2_key)} title={`SHA-256 ${r.xlsx_sha256}`}>
                    Excel
                  </Button>
                  <Button size="sm" onClick={() => void open(r.pdf_r2_key)} title={`SHA-256 ${r.pdf_sha256}`}>
                    PDF
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}

interface ScreeningRow {
  source_id: string;
  regulator: string;
  country: string;
  runs: number;
  ok_runs: number;
  failed_runs: number;
  items_seen: number;
  items_new: number;
  items_matched: number;
  last_run: string | null;
}

function ScreeningLog() {
  const [month, setMonth] = useState(cairoThisMonth());
  const sources = useSources();
  // Counted in the database for the Cairo calendar month (bigint counts arrive as numbers or strings).
  const log = useQuery({
    queryKey: ['screening-log', month],
    queryFn: async () =>
      (
        unwrap<ScreeningRow[] | null>(await supabase.rpc('monthly_screening_log', { p_month: `${month}-01` })) ?? []
      ).map((r) => ({
        ...r,
        runs: Number(r.runs),
        ok_runs: Number(r.ok_runs),
        failed_runs: Number(r.failed_runs),
        items_seen: Number(r.items_seen),
        items_new: Number(r.items_new),
        items_matched: Number(r.items_matched),
      })),
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
        <Field label="Month">
          <Input type="month" value={month} max={cairoThisMonth()} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </Field>
        <p className="small muted">
          Every check of every source in {formatYearMonth(month)} (Cairo time), including checks that found nothing.
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
          <StatRow label={`Screening in ${formatYearMonth(month)}`}>
            <Stat value={sum.runs} label="Checks" />
            <Stat value={sum.failed} label="Failed" tone={sum.failed ? 'danger' : 'quiet'} />
            <Stat value={sum.seen} label="Items read" />
            <Stat value={sum.fresh} label="New" tone="new" />
            <Stat value={sum.matched} label="Matched" tone="warning" />
          </StatRow>
          <Table className="screening">
            <thead>
              <tr>
                <th scope="col">Country</th>
                <th scope="col">Regulator</th>
                <th scope="col">What it reads</th>
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
                const off = s ? !s.enabled : false;
                return (
                  <tr key={r.source_id} className={off ? 'is-off' : undefined}>
                    <td>
                      <Country name={r.country} code={s?.regulator?.country_code ?? null} />
                    </td>
                    <td>{r.regulator}</td>
                    <td className="small">
                      {s ? `${KIND_LABEL[s.kind]} · ${CHANNEL_LABEL[s.channel]}` : '—'}
                      {off ? <span className="muted"> · switched off</span> : null}
                    </td>
                    {r.runs > 0 ? (
                      <>
                        <td className="num mono">{formatNumber(r.runs)}</td>
                        <td className={r.failed_runs ? 'num mono danger' : 'num mono'}>{formatNumber(r.failed_runs)}</td>
                        <td className="num mono">{formatNumber(r.items_seen)}</td>
                        <td className="num mono">{formatNumber(r.items_new)}</td>
                        <td className="num mono">{formatNumber(r.items_matched)}</td>
                        <td className="small mono">{formatDateTime(r.last_run)}</td>
                      </>
                    ) : (
                      <td colSpan={6} className={off ? 'muted small' : 'accent-text small'}>
                        No check recorded this month
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={3}>
                  All sources
                </th>
                <td className="num mono strong">{formatNumber(sum.runs)}</td>
                <td className="num mono strong">{formatNumber(sum.failed)}</td>
                <td className="num mono strong">{formatNumber(sum.seen)}</td>
                <td className="num mono strong">{formatNumber(sum.fresh)}</td>
                <td className="num mono strong">{formatNumber(sum.matched)}</td>
                <td />
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
        lede="The monthly report and the screening log: what was checked, when, and what it found."
      />
      <section className="section">
        <SectionHead index="01" title="Monthly reports" />
        <MonthlyReports />
      </section>
      <section className="section">
        <SectionHead index="02" title="Screening log" />
        <ScreeningLog />
      </section>
    </div>
  );
}
