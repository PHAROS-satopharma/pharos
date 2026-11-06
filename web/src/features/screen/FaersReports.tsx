import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { formatDateTime, formatMonth, formatNumber } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { ErrorNote, Loading } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';

type Listed = 'our_label' | 'reference' | 'not_listed' | 'not_in_reference' | null;

interface FaersReaction {
  reaction: string;
  reports: number;
  last_quarter: number | null;
  quarters: (number | null)[] | null;
  all_reports: number;
  prr: number | null;
  prr_low: number | null;
  prr_high: number | null;
  ror: number | null;
  ror_low: number | null;
  ror_high: number | null;
  chi2: number | null;
  flagged: boolean;
  mesh_ui: string | null;
  listed: Listed;
  /** The other drug over-represented in this reaction's reports (flagged reactions only, 0076, 0078): named in
   *  co_reports of them and in co_all_reports of all the ingredient's reports. */
  co_drug: string | null;
  co_reports: number | null;
  co_all_reports: number | null;
  /** A quarter or more of the reaction's reports could be one patient reported again and again: one sex
   *  (E2B: '1' male, '2' female) and an age within a year of series_age (0081). */
  series_reports: number | null;
  series_age: number | null;
  series_sex: '1' | '2' | null;
}

interface FaersFetch {
  searched: string;
  first_quarter: string;
  last_quarter: string;
  reports: number;
  all_reports: number;
  fetched_at: string;
}

interface Faers {
  fetch: FaersFetch | null;
  reactions: FaersReaction[];
}

function useFaers(ingredientId: string) {
  return useQuery({
    queryKey: ['faers-reports', ingredientId] as const,
    enabled: Boolean(ingredientId),
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Faers> => {
      const [reactions, fetch] = await Promise.all([
        supabase.rpc('ingredient_faers', { p_ingredient: ingredientId }),
        supabase
          .from('faers_ingredient')
          .select('searched, first_quarter, last_quarter, reports, all_reports, fetched_at')
          .eq('ingredient_id', ingredientId)
          .maybeSingle(),
      ]);
      return {
        fetch: unwrap<FaersFetch | null>(fetch),
        reactions: unwrap<FaersReaction[] | null>(reactions) ?? [],
      };
    },
  });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Jul–Sep 2026" for the first day of a quarter. */
function quarterLabel(day: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(day);
  if (!m) return day;
  const i = Number(m[2]) - 1;
  return `${MONTHS[i]}–${MONTHS[i + 2] ?? ''} ${m[1]}`;
}

/** "September 2026": the last month of the quarter that starts on this day. */
function quarterEndMonth(day: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(day);
  if (!m) return day;
  return formatMonth(`${m[1]}-${String(Number(m[2]) + 2).padStart(2, '0')}-01`);
}

/** Every quarter of the period, oldest first, for the first day of the oldest. */
function quarterStarts(first: string, count: number): string[] {
  const m = /^(\d{4})-(\d{2})/.exec(first);
  if (!m) return [];
  let y = Number(m[1]);
  let mo = Number(m[2]);
  const out: string[] = [];
  for (let i = 0; i < count; i += 1) {
    out.push(`${y}-${String(mo).padStart(2, '0')}-01`);
    mo += 3;
    if (mo > 12) {
      mo -= 12;
      y += 1;
    }
  }
  return out;
}

function ratio(n: number | null): string {
  if (n == null) return '–';
  return n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2);
}

/** A part of a whole as a percentage: under 1% is never rounded to 0%. */
function share(part: number, whole: number): string {
  const p = (100 * part) / whole;
  return p < 1 ? '<1%' : `${Math.round(p)}%`;
}

const LISTED: Record<Exclude<Listed, null>, { label: string; tone: 'success' | 'blue' | 'danger'; title: string }> = {
  our_label: { label: 'In our label', tone: 'success', title: 'Section 4.8 of our label names it, or a broader heading above it.' },
  reference: {
    label: 'In the reference label',
    tone: 'blue',
    title: 'Not found in our label; the reference product’s adverse reactions name it, or a broader heading above it.',
  },
  not_listed: {
    label: 'Not in our label',
    tone: 'danger',
    title: 'Neither our label nor the reference label names it or a broader heading.',
  },
  not_in_reference: {
    label: 'Not in the reference label',
    tone: 'danger',
    title: 'The reference product’s adverse reactions do not name it or a broader heading. No label of ours in English is read.',
  },
};

/**
 * Section 06 of the Ingredients screen: FDA adverse event reports (ingredient_faers, 0071 and 0076). The reports to
 * the FDA Adverse Event Reporting System that name the ingredient, counted by openFDA for the last 8 complete
 * quarters (collectors/faers.py, weekly): the most reported reactions, the newest quarter and the whole period, how
 * much more often each is reported with this ingredient than with every other drug (PRR), and whether our label
 * lists it.
 * A report is not proof, and a count is not a rate: the team decides.
 */
export function FaersReports({ ingredientId }: { ingredientId: string }) {
  const q = useFaers(ingredientId);
  const f = q.data?.fetch ?? null;
  const rows = q.data?.reactions ?? [];
  const starts = f ? quarterStarts(f.first_quarter, rows[0]?.quarters?.length ?? 8) : [];
  const whole = f ? `${formatMonth(f.first_quarter)} to ${quarterEndMonth(f.last_quarter)}` : '';
  return (
    <section className="scr-section" aria-label="FDA adverse event reports">
      <SectionHead index="06" title="FDA adverse event reports" aside={q.data && f ? `${rows.length}` : undefined} />
      {q.isPending ? (
        <Loading label="Reading the FDA report counts" />
      ) : q.isError ? (
        <ErrorNote title="The FDA report counts could not be read." error={q.error} onRetry={() => void q.refetch()} />
      ) : !f ? (
        <p className="scr-quiet">
          Not counted yet. The FDA report counts are fetched once a week; this ingredient is counted in the next run.
        </p>
      ) : (
        <>
          <p className="scr-quiet">
            {f.reports
              ? `${formatNumber(f.reports)} reports received by the FDA from ${whole} name ${f.searched}, ` +
                `out of ${formatNumber(f.all_reports)} reports for every drug.`
              : `No report received by the FDA from ${whole} names ${f.searched}.`}{' '}
            Fetched {formatDateTime(f.fetched_at)}.
          </p>
          {rows.length ? (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">Reactions in FDA adverse event reports</caption>
                <thead>
                  <tr>
                    <th>Reaction</th>
                    <th className="num" title={`${quarterLabel(f.last_quarter)}, then ${whole}`}>
                      Reports
                      <div className="scr-quiet">{quarterLabel(f.last_quarter)} / 2 years</div>
                    </th>
                    <th
                      className="num"
                      title="Proportional reporting ratio: how much more often the reaction is reported with this ingredient than with every other drug, with its 95% confidence interval."
                    >
                      PRR (95% CI)
                    </th>
                    <th>Disproportion</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.reaction}>
                      <td>{r.reaction}</td>
                      <td
                        className="num"
                        title={(r.quarters ?? [])
                          .map((n, i) => `${quarterLabel(starts[i] ?? '')}: ${n == null ? 'not known' : formatNumber(n)}`)
                          .join('\n')}
                      >
                        <strong>{r.last_quarter == null ? '–' : formatNumber(r.last_quarter)}</strong>{' '}
                        <span className="scr-quiet">/ {formatNumber(r.reports)}</span>
                      </td>
                      <td className="num">
                        {r.prr == null ? (
                          <span className="scr-quiet">–</span>
                        ) : (
                          <>
                            {ratio(r.prr)}{' '}
                            {r.prr_low != null && r.prr_high != null ? (
                              <span className="scr-quiet">({ratio(r.prr_low)}–{ratio(r.prr_high)})</span>
                            ) : null}
                          </>
                        )}
                      </td>
                      <td>
                        {r.flagged ? (
                          <Tag
                            tone="warning"
                            title="Stands out among this ingredient’s reactions: at least 3 reports, the lower end of the PRR’s 95% interval at least 2, and a PRR at least twice the median PRR of the reactions shown. PHAROS’s own rule, not a published standard."
                          >
                            Disproportionate
                          </Tag>
                        ) : null}
                        {r.flagged && r.series_reports && r.series_age != null && r.series_sex && r.reports ? (
                          <>
                            {' '}
                            <Tag
                              title={
                                `${formatNumber(r.series_reports)} of the ${formatNumber(r.reports)} reports of ` +
                                `${r.reaction} describe ${r.series_sex === '2' ? 'a woman' : 'a man'} aged ` +
                                `${r.series_age - 1} to ${r.series_age + 1}: they could be one patient reported again ` +
                                'and again (follow-ups, or a published case filed by each company). A flag resting on ' +
                                'one patient is weaker than it looks.'
                              }
                            >
                              One case series?
                            </Tag>
                          </>
                        ) : null}
                        {r.flagged && r.co_drug && r.co_reports && r.co_all_reports && r.reports && f.reports ? (
                          <div
                            className="scr-quiet"
                            title={
                              `${formatNumber(r.co_reports)} of the ${formatNumber(r.reports)} reports of ${r.reaction} ` +
                              `naming ${f.searched} also name ${r.co_drug}, against ${formatNumber(r.co_all_reports)} ` +
                              `of all its ${formatNumber(f.reports)} reports. A drug shown here is in at least 3 of ` +
                              'the reaction’s reports and in at least twice its usual share of them: it can be what ' +
                              'the reaction is reported for.'
                            }
                          >
                            Over-represented: {r.co_drug} ({share(r.co_reports, r.reports)} of these reports,{' '}
                            {share(r.co_all_reports, f.reports)} of all {f.searched} reports)
                          </div>
                        ) : null}
                      </td>
                      <td>
                        {r.listed ? (
                          <Tag tone={LISTED[r.listed].tone} title={LISTED[r.listed].title}>
                            {LISTED[r.listed].label}
                          </Tag>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="scr-quiet">
            The reports are FDA’s, from the FDA Adverse Event Reporting System (FAERS), counted through openFDA; the
            reactions are named as FDA publishes them. A report is not proof that the drug caused the reaction, and the
            counts are not how often it happens: most reactions are never reported, and one report can name several
            drugs, so under a flag is the other drug most reported with it that its reports name at least twice as
            often as usual, when there is one. The reactions are matched to MeSH by name for the label; a blank label means MeSH does not have the name or no label is read yet. The
            U.S. Food and Drug Administration does not endorse PHAROS.
          </p>
        </>
      )}
    </section>
  );
}
