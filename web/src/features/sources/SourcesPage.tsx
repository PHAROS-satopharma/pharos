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
        groups.map((g) => (
          <section key={g.country} className="source-group">
            <h2 className="group-title">
              <Country name={g.country} code={g.code} />
              <span className="group-count">
                {g.list.length} {g.list.length === 1 ? 'source' : 'sources'}
              </span>
            </h2>
            <Table className="sources">
              <thead>
                <tr>
                  <th scope="col">Regulator</th>
                  <th scope="col">What it reads</th>
                  <th scope="col">Languages</th>
                  <th scope="col">Health</th>
                  <th scope="col">Last checked</th>
                  <th scope="col">Last published</th>
                  <th scope="col">Last {WINDOW_H} h</th>
                  <th scope="col">Read</th>
                </tr>
              </thead>
              <tbody>
                {g.list.map((s) => {
                  const t = totals.get(s.id);
                  const lastChecked = t?.lastRun ?? s.last_ok_at;
                  return (
                    <tr key={s.id} className={s.enabled ? undefined : 'is-off'}>
                      <td>
                        {s.regulator?.name ?? '—'}
                        {s.origin === 'user' ? (
                          <>
                            {' '}
                            <Tag tone="quiet">Added by hand</Tag>
                          </>
                        ) : null}
                      </td>
                      <td>
                        <div>{KIND_LABEL[s.kind]}</div>
                        <div className="small muted">
                          {CHANNEL_LABEL[s.channel]} ·{' '}
                          <a href={s.url} target="_blank" rel="noopener noreferrer">
                            {hostOf(s.url)}
                          </a>
                        </div>
                      </td>
                      <td className="small">{(s.languages ?? []).map(languageName).join(', ')}</td>
                      <td>
                        <HealthMark health={s.health} />
                        {s.consecutive_failures > 0 ? (
                          <div className="small muted">
                            {s.consecutive_failures} failed {s.consecutive_failures === 1 ? 'check' : 'checks'} in a row
                          </div>
                        ) : null}
                        {t?.lastError ? (
                          <div className="small muted clip" title={t.lastError}>
                            {t.lastError}
                          </div>
                        ) : null}
                      </td>
                      <td className="small" title={formatDateTime(lastChecked)}>
                        {timeAgo(lastChecked)}
                      </td>
                      <td className="small mono" title={formatDateTime(s.last_item_at)}>
                        {s.last_item_at ? formatCairoDate(s.last_item_at) : '—'}
                      </td>
                      <td className="small">
                        {t ? (
                          <span className="mono">
                            {formatNumber(t.runs)} runs
                            {t.failed ? <span className="danger"> · {formatNumber(t.failed)} failed</span> : null}
                            <br />
                            {formatNumber(t.seen)} seen · {formatNumber(t.fresh)} new · {formatNumber(t.matched)} matched
                          </span>
                        ) : runs.isPending ? (
                          '…'
                        ) : (
                          <span className="muted">No run</span>
                        )}
                      </td>
                      <td>
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
        ))
      )}
    </div>
  );
}
