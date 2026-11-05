import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate, formatDateTime, formatNumber, timeAgo } from '../../lib/format';
import { CHANNEL_LABEL, HEALTH_LABEL, KIND_LABEL, hostOf, languageName } from '../../lib/labels';
import type { SourceHealth } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Toggle } from '../../ui/Input';
import { Country } from '../../ui/Flag';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { cx } from '../../ui/cx';
import { HealthMark, Tag } from '../../ui/Tag';
import { PageHead } from '../../ui/Text';
import { Stat, StatRow } from '../../ui/Stat';
import { fetchRuns, totalsBySource, useSources, type SourceWithRegulator } from './queries';
import { AddSource } from './AddSource';

const HEALTH_ORDER: SourceHealth[] = ['down', 'blocked', 'degraded', 'unknown', 'ok'];
const HEALTH_TONE: Record<SourceHealth, string> = {
  ok: 'ok',
  degraded: 'warning',
  down: 'danger',
  blocked: 'neutral',
  unknown: 'quiet',
};
const WINDOW_H = 48;
// Being read but not reading cleanly: the count a country's head flags.
const NEEDS_A_LOOK: SourceHealth[] = ['down', 'blocked', 'degraded'];

export function SourcesPage() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const sources = useSources();
  const [adding, setAdding] = useState(false);
  const [since] = useState(() => new Date(Date.now() - WINDOW_H * 3600_000).toISOString());
  const runs = useQuery({
    queryKey: ['source-runs-recent', since],
    queryFn: () => fetchRuns(since),
  });
  const totals = useMemo(() => totalsBySource(runs.data ?? []), [runs.data]);

  const toggle = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      unwrap<null>(await supabase.from('source').update({ enabled }).eq('id', id));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });

  const groups = useMemo(() => {
    const m = new Map<string, SourceWithRegulator[]>();
    for (const s of sources.data ?? []) {
      const c = s.regulator?.country_name ?? 'Unknown country';
      m.set(c, [...(m.get(c) ?? []), s]);
    }
    return [...m.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([country, list]) => ({
        country,
        code: list[0]?.regulator?.country_code ?? null,
        list: list.sort((a, b) => (a.regulator?.name ?? '').localeCompare(b.regulator?.name ?? '') || a.url.localeCompare(b.url)),
      }));
  }, [sources.data]);

  const summary = useMemo(() => {
    const counts = new Map<SourceHealth, number>();
    for (const s of sources.data ?? []) if (s.enabled) counts.set(s.health, (counts.get(s.health) ?? 0) + 1);
    return HEALTH_ORDER.filter((h) => counts.get(h)).map((h) => ({ health: h, count: counts.get(h) ?? 0 }));
  }, [sources.data]);
  const enabledCount = useMemo(() => (sources.data ?? []).filter((s) => s.enabled).length, [sources.data]);

  return (
    <div className="page">
      <PageHead
        eyebrow="Screening"
        title="Sources"
        lede={`Every channel PHAROS reads, by country. The figures cover the last ${WINDOW_H} hours.`}
        actions={
          isAdmin && !adding ? (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add a source
            </Button>
          ) : null
        }
      />
      {adding ? <AddSource onDone={() => setAdding(false)} /> : null}
      {summary.length > 0 ? (
        <StatRow label="Sources being read, by health">
          <Stat value={enabledCount} label="Being read" />
          {summary.map((h) => (
            <Stat
              key={h.health}
              value={h.count}
              label={HEALTH_LABEL[h.health].label}
              tone={HEALTH_TONE[h.health]}
              title={HEALTH_LABEL[h.health].explain}
            />
          ))}
        </StatRow>
      ) : null}
      {toggle.isError ? <Notice tone="error">Not changed: {errorMessage(toggle.error)}</Notice> : null}
      {runs.isError ? <Notice tone="error">The recent runs could not be read: {errorMessage(runs.error)}</Notice> : null}

      {sources.isPending ? (
        <Loading label="Reading the sources" />
      ) : sources.isError ? (
        <ErrorNote title="The sources could not be loaded." error={sources.error} onRetry={() => void sources.refetch()} />
      ) : groups.length === 0 ? (
        <Empty title="No sources yet.">
          <p>The catalogue of regulators is loaded with the first collector run.</p>
        </Empty>
      ) : (
        groups.map((g) => {
          const attention = g.list.filter((s) => s.enabled && NEEDS_A_LOOK.includes(s.health)).length;
          return (
            <section key={g.country} className="source-group">
              <h2 className="group-title">
                <Country name={g.country} code={g.code} />
                <span className="group-count">
                  {g.list.length} {g.list.length === 1 ? 'source' : 'sources'}
                  {attention > 0 ? <span className="group-alert"> · {attention} {attention === 1 ? 'needs' : 'need'} a look</span> : null}
                </span>
              </h2>
              <Table className="sources">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Health</th>
                    <th scope="col">Activity</th>
                    <th scope="col">Last {WINDOW_H} hours</th>
                    <th scope="col">Read</th>
                  </tr>
                </thead>
                <tbody>
                  {g.list.map((s) => {
                    const t = totals.get(s.id);
                    const lastChecked = t?.lastRun ?? s.last_ok_at;
                    const languages = (s.languages ?? []).map(languageName).join(', ');
                    return (
                      <tr key={s.id} className={cx('source-row', !s.enabled && 'is-off')}>
                        <td className="col-source">
                          <span className="cell-line">
                            <span className="source-name">{s.regulator?.name ?? '—'}</span>
                            {s.origin === 'user' ? <Tag tone="quiet">Added by hand</Tag> : null}
                          </span>
                          <span className="source-kind">{KIND_LABEL[s.kind]}</span>
                          <span className="cell-sub">
                            {CHANNEL_LABEL[s.channel]} ·{' '}
                            <a href={s.url} target="_blank" rel="noopener noreferrer">
                              {hostOf(s.url)}
                            </a>
                            {languages ? <> · {languages}</> : null}
                          </span>
                        </td>
                        <td className="col-health">
                          <HealthMark health={s.health} />
                          {s.consecutive_failures > 0 ? (
                            <span className="cell-sub">
                              {s.consecutive_failures} failed {s.consecutive_failures === 1 ? 'check' : 'checks'} in a row
                            </span>
                          ) : null}
                          {t?.lastError ? (
                            <span className="cell-sub clip" title={t.lastError}>
                              {t.lastError}
                            </span>
                          ) : null}
                        </td>
                        <td className="col-when">
                          <dl className="when">
                            <div>
                              <dt>Checked</dt>
                              <dd title={formatDateTime(lastChecked)}>{timeAgo(lastChecked)}</dd>
                            </div>
                            <div>
                              <dt>Last published</dt>
                              <dd className="mono" title={formatDateTime(s.last_item_at)}>
                                {s.last_item_at ? formatCairoDate(s.last_item_at) : '—'}
                              </dd>
                            </div>
                          </dl>
                        </td>
                        <td className="col-runs">
                          {t ? (
                            <>
                              <dl className="figures">
                                <div>
                                  <dt>Runs</dt>
                                  <dd>{formatNumber(t.runs)}</dd>
                                </div>
                                <div>
                                  <dt>Seen</dt>
                                  <dd>{formatNumber(t.seen)}</dd>
                                </div>
                                <div>
                                  <dt>New</dt>
                                  <dd>{formatNumber(t.fresh)}</dd>
                                </div>
                                <div className={t.matched ? 'is-hit' : undefined}>
                                  <dt>Matched</dt>
                                  <dd>{formatNumber(t.matched)}</dd>
                                </div>
                              </dl>
                              {t.failed ? (
                                <span className="cell-sub danger">
                                  {formatNumber(t.failed)} of {formatNumber(t.runs)} runs failed
                                </span>
                              ) : null}
                            </>
                          ) : runs.isPending ? (
                            <span className="muted">…</span>
                          ) : (
                            <span className="muted">No run</span>
                          )}
                        </td>
                        <td className="col-read">
                          {isAdmin ? (
                            <Toggle
                              checked={s.enabled}
                              disabled={toggle.isPending}
                              onChange={(v) => toggle.mutate({ id: s.id, enabled: v })}
                              label={s.enabled ? 'On' : 'Off'}
                            />
                          ) : (
                            <span>{s.enabled ? 'On' : 'Off'}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            </section>
          );
        })
      )}
    </div>
  );
}
