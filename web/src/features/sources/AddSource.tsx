import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { useRegulators } from '../../lib/regulators';
import { formatDate } from '../../lib/format';
import { CHANNEL_LABEL, KIND_LABEL, SCHEDULE_LABEL, hostOf, languageName } from '../../lib/labels';
import {
  SOURCE_CHANNELS,
  SOURCE_KINDS,
  SOURCE_SCHEDULES,
  type ProbeResult,
  type SourceChannel,
  type SourceKind,
  type SourceSchedule,
} from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Loading, Notice } from '../../ui/States';

interface ProbeItem {
  title: string;
  url: string | null;
  published: string | null;
  lang: string | null;
}

function parseItems(raw: unknown): ProbeItem[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object' && Array.isArray((raw as { items?: unknown }).items)
      ? ((raw as { items: unknown[] }).items)
      : [];
  const out: ProbeItem[] = [];
  for (const it of list) {
    if (!it || typeof it !== 'object') continue;
    const o = it as Record<string, unknown>;
    const title = typeof o.title === 'string' ? o.title : '';
    if (!title) continue;
    out.push({
      title,
      url: typeof o.url === 'string' ? o.url : null,
      published: typeof o.published === 'string' ? o.published : null,
      lang: typeof o.lang === 'string' ? o.lang : null,
    });
  }
  return out;
}

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/^www\./, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
}

const NEW_REG = '__new__';

interface NewRegulator {
  id: string;
  country_code: string;
  country_name: string;
  name: string;
  languages: string;
}

/** Why a new regulator cannot be saved yet, in plain words, or null when it can. */
function checkNewRegulator(r: NewRegulator, langs: string[], known: { id: string }[]): string | null {
  const id = r.id.trim().toUpperCase();
  if (!r.name.trim()) return 'Give the regulator’s name as it writes it.';
  if (!r.country_name.trim()) return 'Give the country.';
  if (!/^[A-Z]{2}$/.test(r.country_code.trim().toUpperCase())) return 'The country code is two letters, e.g. EG.';
  if (!/^[A-Z][A-Z0-9-]{1,15}$/.test(id)) return 'The short code is 2 to 16 capital letters or digits, e.g. EDA.';
  if (known.some((k) => k.id.toUpperCase() === id)) {
    return 'That short code is taken. Choose that regulator from the list instead.';
  }
  if (langs.length === 0) return 'List at least one language code, e.g. ar.';
  if (langs.some((l) => !/^[a-z]{2,3}(-[a-z0-9]{2,8})*$/i.test(l))) return 'Language codes look like ar, en or pt-br.';
  return null;
}

const POLL_MS = 3000;
const GIVE_UP_MS = 10 * 60_000;

export function AddSource({ onDone }: { onDone: () => void }) {
  const { person } = useAuth();
  const qc = useQueryClient();
  const regulators = useRegulators();
  const [url, setUrl] = useState('');
  const [probeId, setProbeId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const [regMode, setRegMode] = useState<'existing' | 'new'>('existing');
  const [regulatorId, setRegulatorId] = useState('');
  const [newReg, setNewReg] = useState<NewRegulator>({ id: '', country_code: '', country_name: '', name: '', languages: '' });
  const [kind, setKind] = useState<SourceKind>('safety');
  const [schedule, setSchedule] = useState<SourceSchedule>('4h');
  const [langs, setLangs] = useState<string[]>([]);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const probe = useQuery({
    queryKey: ['probe', probeId],
    enabled: probeId !== null,
    queryFn: async () =>
      unwrap<ProbeResult | null>(await supabase.from('probe_result').select('*').eq('id', probeId ?? '').maybeSingle()),
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      if (s === 'ok' || s === 'failed') return false;
      if (Date.now() - startedAt > GIVE_UP_MS) return false;
      return POLL_MS;
    },
  });

  const result = probe.data ?? null;
  const items = useMemo(() => parseItems(result?.items), [result?.items]);
  const channel: SourceChannel | null =
    result?.channel_detected && (SOURCE_CHANNELS as string[]).includes(result.channel_detected)
      ? (result.channel_detected as SourceChannel)
      : null;
  const existing = (regulators.data ?? []).find((r) => r.id === regulatorId) ?? null;
  const newLangs = useMemo(
    () => [...new Set(newReg.languages.split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean))],
    [newReg.languages],
  );
  const newRegProblem = regMode === 'new' ? checkNewRegulator(newReg, newLangs, regulators.data ?? []) : null;
  const regLanguages = regMode === 'existing' ? existing?.languages ?? [] : newLangs;
  const regReady = regMode === 'existing' ? existing !== null : newRegProblem === null;

  useEffect(() => {
    setLangs(regLanguages);
    // regLanguages is rebuilt each render; follow the regulator chosen or the languages typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regMode, existing, newReg.languages]);

  useEffect(() => {
    if (channel === 'browser') setSchedule('12h');
  }, [channel]);

  async function start() {
    setStartError(null);
    const u = url.trim();
    try {
      const parsed = new URL(u);
      if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') throw new Error('bad');
    } catch {
      setStartError('That is not a web address. Paste the full link, starting with https://');
      return;
    }
    setStarting(true);
    try {
      const r = await invoke<{ probe_id: string }>('probe-source', { url: u });
      setStartedAt(Date.now());
      setProbeId(r.probe_id);
    } catch (e) {
      setStartError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  }

  async function save() {
    if (!result || !channel || !person || !regReady) return;
    setSaving(true);
    setSaveError(null);
    try {
      let regulatorRowId = existing?.id ?? '';
      let fallbackLangs = existing?.languages ?? [];
      if (regMode === 'new') {
        const regId = newReg.id.trim().toUpperCase();
        unwrap<null>(
          await supabase.from('regulator').insert({
            id: regId,
            country_code: newReg.country_code.trim().toUpperCase(),
            country_name: newReg.country_name.trim(),
            name: newReg.name.trim(),
            languages: newLangs,
          }),
        );
        await qc.invalidateQueries({ queryKey: ['regulators'] });
        // If the source below fails, a second try uses the regulator just made.
        setRegMode('existing');
        setRegulatorId(regId);
        regulatorRowId = regId;
        fallbackLangs = newLangs;
      }
      const parser = result.parser_detected || (['rss', 'atom', 'json'].includes(channel) ? 'feed' : 'generic_html');
      const id = `user-${slug(hostOf(result.url))}-${Date.now().toString(36).slice(-5)}`;
      unwrap<null>(
        await supabase.from('source').insert({
          id,
          regulator_id: regulatorRowId,
          kind,
          channel,
          url: result.url,
          parser,
          languages: langs.length ? langs : fallbackLangs,
          schedule,
          enabled: true,
          origin: 'user',
          notes: notes.trim() || null,
          created_by: person.id,
        }),
      );
      await qc.invalidateQueries({ queryKey: ['sources'] });
      onDone();
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  const timedOut = probeId !== null && result?.status !== 'ok' && result?.status !== 'failed' && Date.now() - startedAt > GIVE_UP_MS;
  const canSave = result?.status === 'ok' && channel !== null && items.length > 0;

  return (
    <section className="panel add-panel" aria-labelledby="add-source-title">
      <div className="panel-head">
        <h2 id="add-source-title" className="panel-title">
          Add a source
        </h2>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <p className="small muted">
        Paste the page or feed where the regulator lists its safety notices. PHAROS reads it once as a test; it is
        saved only if the test finds notices on it.
      </p>
      <div className="inline-form">
        <Field label="Link" className="grow">
          <Input
            type="url"
            value={url}
            placeholder="https://"
            onChange={(e) => {
              setUrl(e.target.value);
              setProbeId(null);
            }}
          />
        </Field>
        <Button variant="primary" busy={starting} disabled={!url.trim()} onClick={() => void start()}>
          Test this link
        </Button>
      </div>
      {startError ? <Notice tone="error">{startError}</Notice> : null}

      {probeId ? (
        probe.isError ? (
          <Notice tone="error">The test result could not be read: {errorMessage(probe.error)}</Notice>
        ) : !result || result.status === 'queued' ? (
          timedOut ? (
            <Notice tone="error">The test has not started after ten minutes. Try again later.</Notice>
          ) : (
            <Loading label="Waiting for the reader to start (this can take a minute)" />
          )
        ) : result.status === 'running' ? (
          timedOut ? (
            <Notice tone="error">The test is taking too long. Try again later.</Notice>
          ) : (
            <Loading label="Reading the page" />
          )
        ) : result.status === 'failed' ? (
          <Notice tone="error">The link could not be read: {result.error ?? 'no reason given'}.</Notice>
        ) : (
          <div className="probe-result">
            <dl className="kv">
              <dt>Read as</dt>
              <dd>{channel ? CHANNEL_LABEL[channel] : `Not recognised (${result.channel_detected ?? 'nothing detected'})`}</dd>
              <dt>Notices found</dt>
              <dd className="mono">{items.length}</dd>
            </dl>
            {items.length === 0 ? (
              <Notice tone="error">The page loaded, but no notices were found on it. It cannot be saved as a source.</Notice>
            ) : (
              <ul className="probe-items">
                {items.slice(0, 12).map((it, i) => (
                  <li key={`${it.url ?? ''}-${i}`}>
                    {it.url ? (
                      <a href={it.url} target="_blank" rel="noopener noreferrer" dir="auto" lang={it.lang ?? undefined}>
                        {it.title}
                      </a>
                    ) : (
                      <span dir="auto" lang={it.lang ?? undefined}>
                        {it.title}
                      </span>
                    )}
                    {it.published ? <span className="mono muted small"> {formatDate(it.published)}</span> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      ) : null}

      {canSave ? (
        <div className="save-source">
          <div className="form-grid">
            <Field label="Regulator">
              <Select
                value={regMode === 'new' ? NEW_REG : regulatorId}
                onChange={(e) => {
                  if (e.target.value === NEW_REG) {
                    setRegMode('new');
                  } else {
                    setRegMode('existing');
                    setRegulatorId(e.target.value);
                  }
                }}
                placeholder="Choose the regulator"
                options={[
                  ...(regulators.data ?? []).map((r) => ({ value: r.id, label: `${r.country_name} — ${r.name}` })),
                  { value: NEW_REG, label: 'A regulator not in the list…' },
                ]}
              />
            </Field>
            <Field label="What it publishes">
              <Select
                value={kind}
                onChange={(e) => setKind(e.target.value as SourceKind)}
                options={SOURCE_KINDS.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
              />
            </Field>
            <Field label="How often to read it">
              <Select
                value={schedule}
                onChange={(e) => setSchedule(e.target.value as SourceSchedule)}
                options={SOURCE_SCHEDULES.map((s) => ({ value: s, label: SCHEDULE_LABEL[s] }))}
              />
            </Field>
          </div>
          {regMode === 'new' ? (
            <fieldset className="new-reg">
              <legend className="field-label">The new regulator</legend>
              <div className="form-grid">
                <Field label="Name, as the regulator writes it">
                  <Input dir="auto" value={newReg.name} onChange={(e) => setNewReg({ ...newReg, name: e.target.value })} />
                </Field>
                <Field label="Country">
                  <Input
                    value={newReg.country_name}
                    placeholder="e.g. Egypt"
                    onChange={(e) => setNewReg({ ...newReg, country_name: e.target.value })}
                  />
                </Field>
                <Field label="Country code" hint="Two letters, ISO 3166 (EU for the European Union).">
                  <Input
                    className="mono"
                    maxLength={2}
                    value={newReg.country_code}
                    onChange={(e) => setNewReg({ ...newReg, country_code: e.target.value.toUpperCase() })}
                  />
                </Field>
                <Field label="Short code" hint="Capital letters, used inside PHAROS, e.g. EDA.">
                  <Input
                    className="mono"
                    maxLength={16}
                    value={newReg.id}
                    onChange={(e) => setNewReg({ ...newReg, id: e.target.value.toUpperCase() })}
                  />
                </Field>
                <Field
                  label="Languages it publishes in"
                  hint={newLangs.length ? newLangs.map(languageName).join(', ') : 'Language codes, e.g. ar, en'}
                >
                  <Input
                    className="mono"
                    value={newReg.languages}
                    onChange={(e) => setNewReg({ ...newReg, languages: e.target.value })}
                  />
                </Field>
              </div>
              {newRegProblem ? <p className="small muted">{newRegProblem}</p> : null}
            </fieldset>
          ) : null}
          {regLanguages.length > 0 ? (
            <fieldset className="langs">
              <legend className="field-label">Languages this source publishes in</legend>
              {regLanguages.map((l) => (
                <Toggle
                  key={l}
                  checked={langs.includes(l)}
                  onChange={(v) => setLangs((cur) => (v ? [...cur, l] : cur.filter((x) => x !== l)))}
                  label={languageName(l)}
                />
              ))}
            </fieldset>
          ) : null}
          <Field label="Notes (optional)">
            <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
          {saveError ? <Notice tone="error">Not saved: {saveError}</Notice> : null}
          <div className="panel-foot">
            <Button variant="primary" busy={saving} disabled={!regReady} onClick={() => void save()}>
              Save this source
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
