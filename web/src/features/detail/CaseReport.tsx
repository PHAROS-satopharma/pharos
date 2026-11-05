import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { formatDate } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Tag } from '../../ui/Tag';

export interface CaseReportRow {
  issue_id: string;
  title: string;
  status: string;
  url: string;
  lang: string | null;
  pmid: string | null;
  journal: string | null;
  flagged_by: 'pubtype' | 'title';
  day_zero: string;
  serious_due: string;
  nonserious_due: string;
  ingredients: string[] | null;
  not_monitored: string[] | null;
}

export function useCaseReport(issueId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['case-report', issueId],
    enabled,
    queryFn: async () =>
      (unwrap<CaseReportRow[] | null>(await supabase.from('v_case_report').select('*').eq('issue_id', issueId)) ?? [])[0] ?? null,
  });
}

/** On a literature notice that looks like a case report: day zero, the two reporting dates, and EMA's monitoring. */
export function CaseReport({ issueId, enabled }: { issueId: string; enabled: boolean }) {
  const q = useCaseReport(issueId, enabled);
  const c = q.data;
  if (!c) return null;
  const monitored = (c.ingredients ?? []).filter((i) => !(c.not_monitored ?? []).includes(i));
  return (
    <section className="panel case-report" aria-labelledby="case-report-title">
      <div className="panel-head">
        <h2 id="case-report-title" className="panel-title">
          Possible case report
        </h2>
        <Tag tone="warning" title={c.flagged_by === 'pubtype' ? 'PubMed lists it as a case report.' : 'Its title reads like a case report.'}>
          {c.flagged_by === 'pubtype' ? 'PubMed: Case Reports' : 'From its title'}
        </Tag>
      </div>
      <p className="small">
        If it describes a valid case with one of our products, it is an individual case safety report. Day zero is the day
        PHAROS found it.
      </p>
      <dl className="case-report-dates">
        <div>
          <dt>Day zero</dt>
          <dd>{formatDate(c.day_zero)}</dd>
        </div>
        <div>
          <dt>Serious: report by</dt>
          <dd>{formatDate(c.serious_due)}</dd>
        </div>
        <div>
          <dt>Non-serious: report by</dt>
          <dd>{formatDate(c.nonserious_due)}</dd>
        </div>
      </dl>
      {(c.not_monitored ?? []).length > 0 ? (
        <p className="small">
          <Tag tone="danger">Not monitored by EMA</Tag> {c.not_monitored?.join(', ')} is not on EMA’s medical literature
          monitoring list, so a case from this paper is ours to report.
        </p>
      ) : null}
      {monitored.length > 0 ? (
        <p className="small soft">
          EMA monitors the literature for {monitored.join(', ')} and enters the cases it finds into EudraVigilance.
        </p>
      ) : null}
      {c.pmid ? (
        <p className="small soft">
          PMID <span className="mono">{c.pmid}</span>
          {c.journal ? ` · ${c.journal}` : ''}
        </p>
      ) : null}
    </section>
  );
}
