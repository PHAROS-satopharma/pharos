import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useSources } from '../sources/queries';
import { unwrap } from '../../lib/api';
import { cairoToday, formatCairoDate, formatDate, formatMonth } from '../../lib/format';
import { HEALTH_LABEL } from '../../lib/labels';
import { supabase } from '../../lib/supabase';
import { ErrorNote, Loading } from '../../ui/States';
import { Stat, StatRow } from '../../ui/Stat';
import { Table } from '../../ui/Table';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import type { CaseReportRow } from '../detail/CaseReport';

export interface OverdueItem {
  kind: 'signal' | 'review' | 'psur';
  ref_id: string;
  label: string | null;
  title: string;
  ingredient: string | null;
  due: string;
  days_late: number;
}

function useOverdue() {
  return useQuery({
    queryKey: ['overdue-items'],
    queryFn: async () => unwrap<OverdueItem[] | null>(await supabase.rpc('overdue_items')) ?? [],
  });
}

function useCounts() {
  return useQuery({
    queryKey: ['oversight-counts'],
    queryFn: async () => {
      const [fresh, open, report] = await Promise.all([
        supabase.from('issue').select('id', { count: 'exact', head: true }).eq('status', 'new').eq('is_backfill', false),
        supabase.from('signal').select('id', { count: 'exact', head: true }).neq('stage', 'closed'),
        supabase.from('monthly_report').select('month,generated_at').order('month', { ascending: false }).limit(1),
      ]);
      if (fresh.error) throw fresh.error;
      if (open.error) throw open.error;
      return {
        awaiting: fresh.count ?? 0,
        openSignals: open.count ?? 0,
        lastReport: (unwrap<{ month: string; generated_at: string }[] | null>(report) ?? [])[0] ?? null,
      };
    },
  });
}

function useOpenCaseReports() {
  return useQuery({
    queryKey: ['case-reports-open'],
    queryFn: async () =>
      unwrap<CaseReportRow[] | null>(
        await supabase.from('v_case_report').select('*').in('status', ['new', 'reviewed', 'relevant']).order('day_zero', { ascending: false }).limit(50),
      ) ?? [],
  });
}

function daysTo(day: string, today: string): number {
  return Math.round((Date.parse(day) - Date.parse(today)) / 86_400_000);
}

function late(days: number): string {
  return days === 1 ? '1 day late' : `${days} days late`;
}

function left(days: number): string {
  if (days === 0) return 'Today';
  return days === -1 ? 'In 1 day' : `In ${-days} days`;
}

function LateTable({ rows }: { rows: OverdueItem[] }) {
  return (
    <Table>
      <thead>
        <tr>
          <th scope="col">What</th>
          <th scope="col">Ingredient</th>
          <th scope="col">Due</th>
          <th scope="col">Late</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.kind}-${r.ref_id}-${r.due}`}>
            <td>
              <Link to={r.kind === 'signal' ? `/signals/${r.ref_id}` : `/issue/${r.ref_id}`} className="title-link" dir="auto">
                {r.kind === 'signal' ? `${r.label} · ${r.title}` : r.title}
              </Link>
              <span className="cell-sub">{r.kind === 'signal' ? 'Signal step' : 'Notice to review'}</span>
            </td>
            <td>{r.ingredient ?? '—'}</td>
            <td>{formatDate(r.due)}</td>
            <td>
              <Tag tone={r.days_late > 7 ? 'danger' : 'warning'}>{late(r.days_late)}</Tag>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export function OversightPage() {
  const overdue = useOverdue();
  const counts = useCounts();
  const sources = useSources();
  const cases = useOpenCaseReports();
  const today = cairoToday();
  const liveCases = (cases.data ?? []).filter((c) => c.nonserious_due >= today);

  const rows = overdue.data ?? [];
  const lateRows = rows.filter((r) => r.kind !== 'psur');
  const lateSignals = lateRows.filter((r) => r.kind === 'signal').length;
  const lateReviews = lateRows.filter((r) => r.kind === 'review').length;
  const psur = rows.filter((r) => r.kind === 'psur').sort((a, b) => a.due.localeCompare(b.due));
  const troubled = (sources.data ?? []).filter((s) => s.enabled && s.health !== 'ok' && s.health !== 'unknown');

  return (
    <div className="page">
      <PageHead
        eyebrow="Oversight"
        title="Oversight"
        lede="For the QPPV: what is late, what is coming due, and whether every source is being read. Late items also go to the administrators on Telegram each morning."
      />

      <StatRow label="At a glance">
        <Stat value={counts.data?.awaiting} label="Notices to review" tone="new" />
        <Stat value={overdue.data ? lateReviews : null} label="Reviews late" tone={lateReviews ? 'danger' : 'ok'} />
        <Stat value={counts.data?.openSignals} label="Open signals" tone="warning" />
        <Stat value={overdue.data ? lateSignals : null} label="Signal steps late" tone={lateSignals ? 'danger' : 'ok'} />
        <Stat value={sources.data ? troubled.length : null} label="Sources needing a look" tone={troubled.length ? 'warning' : 'ok'} />
        <Stat value={overdue.data ? psur.length : null} label="PSUR dates in 90 days" tone="quiet" />
      </StatRow>
      {counts.isError ? <ErrorNote error={counts.error} onRetry={() => void counts.refetch()} /> : null}

      <section className="section">
        <SectionHead index="01" title="Late" aside={<Link to="/signals">All signals</Link>} />
        {overdue.isPending ? (
          <Loading label="Reading what is late" />
        ) : overdue.isError ? (
          <ErrorNote error={overdue.error} onRetry={() => void overdue.refetch()} />
        ) : lateRows.length === 0 ? (
          <p className="soft">Nothing is late. Every signal step is within its due date and every notice was reviewed in time.</p>
        ) : (
          <LateTable rows={lateRows} />
        )}
      </section>

      <section className="section">
        <SectionHead index="02" title="Literature case reports" />
        <p className="soft small">
          Papers that look like individual case reports, with day zero (the day PHAROS found them) and the dates to report a
          valid case: 15 days if serious, 90 if not. Shown until the 90 days pass, unless judged not relevant.
        </p>
        {cases.isPending ? (
          <Loading label="Reading the case reports" />
        ) : cases.isError ? (
          <ErrorNote error={cases.error} onRetry={() => void cases.refetch()} />
        ) : liveCases.length === 0 ? (
          <p className="soft">No literature case report is within its reporting time.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th scope="col">Paper</th>
                <th scope="col">Day zero</th>
                <th scope="col">Serious by</th>
                <th scope="col">Non-serious by</th>
                <th scope="col">EMA monitors</th>
              </tr>
            </thead>
            <tbody>
              {liveCases.map((c) => {
                const daysLeft = daysTo(c.serious_due, today);
                return (
                  <tr key={c.issue_id}>
                    <td>
                      <Link to={`/issue/${c.issue_id}`} className="title-link" dir="auto" lang={c.lang ?? undefined}>
                        {c.title}
                      </Link>
                      <span className="cell-sub">{(c.ingredients ?? []).join(', ')}</span>
                    </td>
                    <td>{formatDate(c.day_zero)}</td>
                    <td>
                      {formatDate(c.serious_due)}
                      {daysLeft >= 0 ? (
                        <span className="cell-sub">{daysLeft === 0 ? 'Today' : `${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left`}</span>
                      ) : (
                        <span className="cell-sub">Passed</span>
                      )}
                    </td>
                    <td>{formatDate(c.nonserious_due)}</td>
                    <td>
                      {(c.not_monitored ?? []).length > 0 ? (
                        <Tag tone="danger">No: {c.not_monitored?.join(', ')}</Tag>
                      ) : (
                        <Tag tone="success">Yes</Tag>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </section>

      <section className="section">
        <SectionHead index="03" title="PSUR dates in the next 90 days" aside={<Link to="/psur">PSUR builder</Link>} />
        {overdue.isPending ? null : psur.length === 0 ? (
          <p className="soft">No EURD data lock point or submission date of a watched ingredient falls in the next 90 days.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Ingredient</th>
                <th scope="col">What</th>
                <th scope="col">Procedure</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {psur.map((r) => (
                <tr key={`${r.label}-${r.title}-${r.due}`}>
                  <td>{formatDate(r.due)}</td>
                  <td>{r.ingredient}</td>
                  <td>{r.title}</td>
                  <td className="mono small">{r.label ?? '—'}</td>
                  <td>{left(r.days_late)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>

      <section className="section">
        <SectionHead index="04" title="Sources needing a look" aside={<Link to="/sources">All sources</Link>} />
        {sources.isPending ? (
          <Loading label="Reading the sources" />
        ) : sources.isError ? (
          <ErrorNote error={sources.error} onRetry={() => void sources.refetch()} />
        ) : troubled.length === 0 ? (
          <p className="soft">Every source in use was read without trouble on its last check.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Country</th>
                <th scope="col">State</th>
                <th scope="col">Last read well</th>
              </tr>
            </thead>
            <tbody>
              {troubled.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.regulator?.name ?? s.id}
                    <span className="cell-sub mono">{s.id}</span>
                  </td>
                  <td>{s.regulator?.country_name ?? '—'}</td>
                  <td>
                    <Tag tone={s.health === 'down' || s.health === 'blocked' ? 'danger' : 'warning'} title={HEALTH_LABEL[s.health]?.explain}>
                      {HEALTH_LABEL[s.health]?.label ?? s.health}
                    </Tag>
                  </td>
                  <td>{s.last_ok_at ? formatCairoDate(s.last_ok_at) : 'Never'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>

      <section className="section">
        <SectionHead index="05" title="Monthly report" aside={<Link to="/reports">Reports</Link>} />
        {counts.isPending ? null : counts.data?.lastReport ? (
          <p>
            The latest is <strong>{formatMonth(counts.data.lastReport.month)}</strong>, made{' '}
            {formatCairoDate(counts.data.lastReport.generated_at)}.
          </p>
        ) : (
          <p className="soft">No monthly report has been made yet. The first covers November 2026.</p>
        )}
      </section>
    </div>
  );
}
