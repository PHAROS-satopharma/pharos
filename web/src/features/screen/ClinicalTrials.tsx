import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { formatDate, formatDateTime, formatMonth, formatNumber } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { ErrorNote, Loading } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';

interface Trial {
  nct_id: string;
  title: string;
  phase: string[] | null;
  status: string;
  previous_status: string | null;
  status_changed_on: string | null;
  start_date: string | null;
  completion_date: string | null;
  sponsor: string | null;
  enrolment: number | null;
  enrolment_type: string | null;
  has_results: boolean;
  results_posted_on: string | null;
  last_update_on: string | null;
  new_results: boolean;
  status_changed: boolean;
}

interface TrialEvent {
  term: string;
  organ_systems: string[];
  trials: number;
  affected: number;
  at_risk: number | null;
}

interface Trials {
  searched: { at: string; names: string[]; trials: number } | null;
  with_results: number;
  recent: number;
  trials: Trial[];
  events: TrialEvent[];
}

function useTrials(ingredientId: string) {
  return useQuery({
    queryKey: ['clinical-trials', ingredientId] as const,
    enabled: Boolean(ingredientId),
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Trials> =>
      unwrap<Trials>(await supabase.rpc('ingredient_trials', { p_ingredient: ingredientId })),
  });
}

type Tone = 'neutral' | 'blue' | 'warning' | 'danger' | 'quiet';

/** The registry's overall status in plain words. */
const STATUS: Record<string, { label: string; tone: Tone }> = {
  RECRUITING: { label: 'Recruiting', tone: 'blue' },
  NOT_YET_RECRUITING: { label: 'Not yet recruiting', tone: 'quiet' },
  ENROLLING_BY_INVITATION: { label: 'Enrolling by invitation', tone: 'blue' },
  ACTIVE_NOT_RECRUITING: { label: 'Active, not recruiting', tone: 'neutral' },
  COMPLETED: { label: 'Completed', tone: 'neutral' },
  SUSPENDED: { label: 'Suspended', tone: 'warning' },
  TERMINATED: { label: 'Terminated', tone: 'danger' },
  WITHDRAWN: { label: 'Withdrawn', tone: 'warning' },
  UNKNOWN: { label: 'Status unknown', tone: 'quiet' },
};

function statusWords(s: string | null): string {
  if (!s) return '–';
  const known = STATUS[s];
  if (known) return known.label;
  const words = s.replace(/_/g, ' ').toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "Phase 2/3", "Early phase 1", "Not applicable" (a study that is not a drug trial phase). */
function phaseWords(phase: string[] | null): string {
  if (!phase?.length) return '–';
  if (phase.includes('NA')) return 'Not applicable';
  if (phase.includes('EARLY_PHASE1')) return 'Early phase 1';
  const n = phase.map((p) => p.replace('PHASE', '')).filter(Boolean);
  return `Phase ${n.join('/')}`;
}

/** A registry date as published: a day ("4 Apr 2016") or a month ("November 2005"). */
function registryDate(d: string | null): string {
  if (!d) return '–';
  return /^\d{4}-\d{2}$/.test(d) ? formatMonth(`${d}-01`) : formatDate(d);
}

const SHOWN = 25;

/**
 * Section 07 of the Ingredients screen: the clinical trials whose interventions name the ingredient, from
 * ClinicalTrials.gov (ingredient_trials, 0067), newest update first, with what changed in the last 90 days, and
 * the serious adverse events most reported across the trials with results. The events are the sponsors' words as
 * published, summed over every arm (comparators and placebo too): a reason to open the trial, not a finding.
 */
export function ClinicalTrials({ ingredientId }: { ingredientId: string }) {
  const q = useTrials(ingredientId);
  const [all, setAll] = useState(false);
  const data = q.data;
  const trials = data?.trials ?? [];
  const events = data?.events ?? [];
  const shown = all ? trials : trials.slice(0, SHOWN);
  return (
    <section className="scr-section" aria-label="Clinical trials">
      <SectionHead index="07" title="Clinical trials" aside={data ? formatNumber(trials.length) : undefined} />
      {q.isPending ? (
        <Loading label="Reading the clinical trials" />
      ) : q.isError ? (
        <ErrorNote title="The clinical trials could not be read." error={q.error} onRetry={() => void q.refetch()} />
      ) : !data?.searched ? (
        <p className="scr-quiet">
          Not searched yet. The weekly PHAROS clinical trials run looks this ingredient up on ClinicalTrials.gov.
        </p>
      ) : (
        <>
          <p className="scr-quiet">
            {trials.length
              ? `${formatNumber(trials.length)} ${trials.length === 1 ? 'trial' : 'trials'}, ` +
                `${formatNumber(data.with_results)} with results posted; ` +
                `${formatNumber(data.recent)} changed status or posted results in the last 90 days.`
              : 'ClinicalTrials.gov lists no trial whose interventions name this ingredient.'}
          </p>
          {trials.length ? (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">Clinical trials, newest update first</caption>
                <thead>
                  <tr>
                    <th>Trial</th>
                    <th>Phase</th>
                    <th>Status</th>
                    <th className="num">Enrolment</th>
                    <th>Start – completion</th>
                    <th>Last update</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((t) => (
                    <tr key={t.nct_id}>
                      <td>
                        <a href={`https://clinicaltrials.gov/study/${t.nct_id}`} target="_blank" rel="noopener noreferrer">
                          {t.title}
                        </a>
                        <div className="scr-quiet">
                          {t.nct_id}
                          {t.sponsor ? ` · ${t.sponsor}` : ''}
                        </div>
                      </td>
                      <td>{phaseWords(t.phase)}</td>
                      <td>
                        <Tag
                          tone={STATUS[t.status]?.tone ?? 'neutral'}
                          title={
                            t.status_changed && t.previous_status
                              ? `Was ${statusWords(t.previous_status).toLowerCase()} until ${formatDate(t.status_changed_on)}`
                              : undefined
                          }
                        >
                          {statusWords(t.status)}
                        </Tag>{' '}
                        {t.status_changed ? (
                          <Tag
                            tone="warning"
                            title={`Changed from ${statusWords(t.previous_status).toLowerCase()} on ${formatDate(t.status_changed_on)}`}
                          >
                            Status changed
                          </Tag>
                        ) : null}{' '}
                        {t.new_results ? (
                          <Tag tone="warning" title={`Results first posted ${formatDate(t.results_posted_on)}`}>
                            New results
                          </Tag>
                        ) : t.has_results ? (
                          <Tag tone="blue" title={t.results_posted_on ? `First posted ${formatDate(t.results_posted_on)}` : undefined}>
                            Results posted
                          </Tag>
                        ) : null}
                      </td>
                      <td className="num">
                        {formatNumber(t.enrolment)}
                        {t.enrolment != null && t.enrolment_type === 'ESTIMATED' ? (
                          <div className="scr-quiet">estimated</div>
                        ) : null}
                      </td>
                      <td>
                        {registryDate(t.start_date)} – {registryDate(t.completion_date)}
                      </td>
                      <td>{formatDate(t.last_update_on)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {trials.length > SHOWN ? (
            <Button size="sm" onClick={() => setAll((v) => !v)}>
              {all ? `Show the first ${SHOWN}` : `Show all ${formatNumber(trials.length)}`}
            </Button>
          ) : null}
          {events.length ? (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">Serious adverse events across the trials with results</caption>
                <thead>
                  <tr>
                    <th>Serious adverse event</th>
                    <th className="num">Trials</th>
                    <th className="num">Participants affected</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.term.toLowerCase()}>
                      <td>
                        {e.term}
                        {e.organ_systems.length ? <div className="scr-quiet">{e.organ_systems.join(' · ')}</div> : null}
                      </td>
                      <td className="num">{formatNumber(e.trials)}</td>
                      <td className="num">
                        <strong>{formatNumber(e.affected)}</strong>
                        {e.at_risk ? <span className="scr-quiet"> of {formatNumber(e.at_risk)}</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : data.with_results ? (
            <p className="scr-quiet">The trials with results report no serious adverse event.</p>
          ) : null}
          <p className="scr-quiet">
            Trials whose interventions name {data.searched.names.join(', ')}, searched {formatDateTime(data.searched.at)}.
            The serious adverse events are the sponsors’ words as published, summed over every arm of each trial, the
            comparators and placebo included. Data from ClinicalTrials.gov (U.S. National Library of Medicine), which
            does not endorse PHAROS.
          </p>
        </>
      )}
    </section>
  );
}
