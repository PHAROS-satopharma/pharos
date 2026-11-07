import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import '../../styles/sources.css';
import { supabase } from '../../lib/supabase';
import { downloadArchived, errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate, formatDate, formatDateTime, formatNumber, timeAgo } from '../../lib/format';
import { CHANNEL_LABEL, DOC_TYPE_LABEL, HEALTH_LABEL, SCHEDULE_LABEL } from '../../lib/labels';
import { safeHref } from '../../lib/safeHref';
import type { SourceHealth } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Toggle } from '../../ui/Input';
import { Country } from '../../ui/Flag';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { HealthMark, Tag } from '../../ui/Tag';
import { PageHead } from '../../ui/Text';
import { Stat, StatRow } from '../../ui/Stat';
import {
  fetchRuns,
  totalsBySource,
  useFiltered,
  useSources,
  type FilteredSummary,
  type RunTotals,
  type SourceWithRegulator,
} from './queries';
import { AddSource } from './AddSource';
import { useLabelWatchSources, watchLine } from './labelWatchLine';
import { listLine, useListChecks, type ListCheckRow } from './listCheck';
import {
  MAX_LOOKBACK_DAYS,
  OTHER_AUTHORITIES,
  countryCards,
  lastLook,
  listsItems,
  newSince,
  pageStatus,
  sinceFor,
  offReason,
  sourceLabels,
  sourcePage,
  waitingForMail,
  type CountryCard,
  type NewItem,
  type PageKind,
  type RegulatorPage,
} from './horizontal';
import { countNew, useHorizontal, useMarkLooked, useRegulatorPages, type HorizontalData } from './newItems';

const PAGE_KIND_LABEL: Record<PageKind, string> = {
  database: 'Drug database',
  dhpc: 'DHPC',
  safety: 'Safety notifications',
};
const HEALTH_ORDER: SourceHealth[] = ['down', 'blocked', 'degraded', 'unknown', 'ok'];
const HEALTH_TONE: Record<SourceHealth, string> = {
  ok: 'ok',
  degraded: 'warning',
  down: 'danger',
  blocked: 'neutral',
  unknown: 'quiet',
};
// Being read but not reading cleanly: worth a mark beside the source's name.
const NEEDS_A_LOOK: SourceHealth[] = ['down', 'blocked', 'degraded'];

type Card = CountryCard<SourceWithRegulator>;

interface CardShared {
  hz: HorizontalData;
  /** What each source's filters left out (filtered_item); read only with the technical details on. */
  filtered: Map<string, FilteredSummary>;
  /** Each source's latest weekly list check (list_check): its own list against what is stored. */
  lists: Map<string, ListCheckRow>;
  totals: Map<string, RunTotals>;
  runsPending: boolean;
  isAdmin: boolean;
  technical: boolean;
  onToggle: (id: string, enabled: boolean) => void;
  toggling: boolean;
}

export function SourcesPage() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const sources = useSources();
  const pages = useRegulatorPages();
  const hz = useHorizontal();
  const [adding, setAdding] = useState(false);
  const [technical, setTechnical] = useState(false);
  const weekIso = hz.weekStart.toISOString();
  const runs = useQuery({
    queryKey: ['source-runs-week', weekIso],
    queryFn: () => fetchRuns(weekIso),
  });
  const totals = useMemo(() => totalsBySource(runs.data ?? []), [runs.data]);
  const filtered = useFiltered(isAdmin && technical);
  const lists = useListChecks();

  const toggle = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => {
      unwrapChanged(await supabase.from('source').update({ enabled }).eq('id', id).select('id'), 'this source');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });

  const cards = useMemo(
    () => countryCards(hz.regulators, pages.data ?? [], sources.data ?? []),
    [hz.regulators, pages.data, sources.data],
  );
  const summary = useMemo(() => {
    const counts = new Map<SourceHealth, number>();
    for (const s of sources.data ?? []) if (s.enabled) counts.set(s.health, (counts.get(s.health) ?? 0) + 1);
    return HEALTH_ORDER.filter((h) => counts.get(h)).map((h) => ({ health: h, count: counts.get(h) ?? 0 }));
  }, [sources.data]);
  const totalNew = countNew(hz);
  const failed = sources.error ?? pages.error ?? hz.error;
  const loading = sources.isPending || pages.isPending || hz.isPending;
  const shared: CardShared = {
    hz,
    filtered: filtered.data ?? new Map(),
    lists: lists.data ?? new Map(),
    totals,
    runsPending: runs.isPending,
    isAdmin,
    technical: isAdmin && technical,
    onToggle: (id, enabled) => toggle.mutate({ id, enabled }),
    toggling: toggle.isPending,
  };

  return (
    <div className="page">
      <PageHead
        eyebrow="Screening"
        title="Sources"
        lede="The pages you check for each authority, and what the authorities published since you last looked. Weeks run Sunday to Saturday, Cairo time."
        actions={
          isAdmin ? (
            <>
              <Toggle checked={technical} onChange={setTechnical} label="Technical details" />
              {!adding ? (
                <Button variant="primary" onClick={() => setAdding(true)}>
                  Add a source
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      {adding ? <AddSource onDone={() => setAdding(false)} /> : null}
      {shared.technical && summary.length > 0 ? (
        <StatRow label="Sources being read, by health">
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
      {runs.isError ? <Notice tone="error">This week's checks could not be read: {errorMessage(runs.error)}</Notice> : null}

      {failed ? (
        <ErrorNote
          title="The sources could not be loaded."
          error={failed}
          onRetry={() => {
            void sources.refetch();
            void pages.refetch();
            void qc.invalidateQueries({ queryKey: ['regulators'] });
            void qc.invalidateQueries({ queryKey: ['my-country-look'] });
            void qc.invalidateQueries({ queryKey: ['new-items'] });
          }}
        />
      ) : loading ? (
        <Loading label="Reading the authorities' pages" />
      ) : cards.hers.length + cards.others.length === 0 ? (
        <Empty title="No sources yet.">
          <p>The catalogue of authorities is loaded with the first collector run.</p>
        </Empty>
      ) : (
        <>
          <p className="hz-lede-new">
            {totalNew > 0 ? (
              <>
                <strong>{formatNumber(totalNew)} new</strong> since you last looked, across every country.
              </>
            ) : (
              'Nothing new since you last looked.'
            )}
          </p>
          {cards.hers.map((c) => (
            <CountryCardView key={c.country} card={c} {...shared} />
          ))}
          {cards.others.length > 0 ? (
            <>
              <h2 className="hz-section-title">{OTHER_AUTHORITIES}</h2>
              {cards.others.map((c) => (
                <CountryCardView key={c.country} card={c} {...shared} />
              ))}
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

function CountryCardView({ card, hz, ...rest }: CardShared & { card: Card }) {
  const mark = useMarkLooked();
  const regIds = card.regulators.map((r) => r.id);
  const look = lastLook(card, hz.looks);
  const since = sinceFor(look, hz.weekStart, hz.now);
  const fresh = newSince(hz.items, regIds, since);
  const week = newSince(hz.items, regIds, hz.weekStart);
  const sourcesById = new Map(card.sources.map((s) => [s.id, s]));
  const capped = since.getTime() > (look ? Date.parse(look) : hz.weekStart.getTime());
  const sinceWords = capped
    ? `in the last ${MAX_LOOKBACK_DAYS} days`
    : look
      ? `since ${formatDateTime(look)}, when you last looked`
      : `since ${formatDateTime(hz.weekStart.toISOString())}, the start of this week`;
  const headingId = `hz-${card.regulators[0]?.id ?? card.country}`;
  const multi = card.regulators.length > 1;

  return (
    <section className="hz-card" aria-labelledby={headingId}>
      <header className="hz-head">
        <h2 className="hz-country" id={headingId}>
          <Country name={card.country} code={card.code} />
        </h2>
        <p className="hz-regs">{card.regulators.map((r) => r.name).join(' · ')}</p>
      </header>

      {card.pages.length > 0 ? (
        <div className="hz-block">
          <h3 className="hz-block-title">The pages you check</h3>
          <ul className="hz-pages">
            {card.pages.map((p) => (
              <PageLine key={p.id} page={p} sources={sourcesById} />
            ))}
          </ul>
        </div>
      ) : null}

      <div className="hz-block">
        <div className="hz-new-head">
          <h3 className="hz-new-title">
            New since you last looked <span className="hz-n">({formatNumber(fresh.length)})</span>
            <span className="hz-since">{sinceWords}</span>
          </h3>
          <Button
            busy={mark.isPending}
            disabled={!hz.readAt}
            onClick={() =>
              regIds[0] && hz.readAt ? mark.mutate({ regulatorId: regIds[0], readAt: hz.readAt }) : undefined
            }
          >
            Mark as looked at
          </Button>
        </div>
        {mark.isError ? <Notice tone="error">Not marked: {errorMessage(mark.error)}</Notice> : null}
        {fresh.length === 0 ? (
          <p className="hz-nothing">Nothing new since {formatDateTime(since.toISOString())}.</p>
        ) : (
          <ItemList items={fresh} showAuthority={multi} />
        )}
      </div>

      <div className="hz-block">
        <WeekFigures card={card} week={week} {...rest} />
      </div>
    </section>
  );
}

function PageLine({ page, sources }: { page: RegulatorPage; sources: Map<string, SourceWithRegulator> }) {
  const status = pageStatus(page, sources);
  const href = safeHref(page.url);
  const watch = useLabelWatchSources();
  const watched = page.kind === 'database' && watch.data ? watchLine(page.read_by, watch.data) : null;
  return (
    <li className={cx('hz-page', `is-${status.state}`)}>
      {href ? (
        <a className="hz-page-link" href={href} target="_blank" rel="noopener noreferrer">
          {page.label}
        </a>
      ) : (
        <span className="hz-page-link">{page.label}</span>
      )}
      <span className="hz-page-kind">{PAGE_KIND_LABEL[page.kind]}</span>
      <span className="hz-read">{status.label}</span>
      {status.note ? <span className="hz-note">{status.note}</span> : null}
      {watched ? <span className="hz-note">{watched}</span> : null}
    </li>
  );
}

function ItemList({ items, showAuthority }: { items: NewItem[]; showAuthority: boolean }) {
  return (
    <ol className="hz-items">
      {items.map((i) => {
        const href = safeHref(i.link);
        return (
          <li key={i.document_id} className={cx('hz-item', i.matched && 'is-hit')}>
            <div className="hz-item-meta">
              <span className="hz-item-date" title={`First seen ${formatDateTime(i.first_seen_at)}`}>
                {i.published_date ? formatDate(i.published_date) : `Found ${formatCairoDate(i.first_seen_at)}`}
              </span>
              {i.doc_type !== 'other' ? <span>{DOC_TYPE_LABEL[i.doc_type]}</span> : null}
              {showAuthority ? <span>{i.regulator_name}</span> : null}
              {i.matched ? <Tag tone="warning">Matches a watched ingredient</Tag> : null}
            </div>
            <p className="hz-item-title" lang={i.lang ?? undefined}>
              {href ? (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  {i.title_orig}
                </a>
              ) : (
                i.title_orig
              )}
            </p>
            {!href && (i.email_id || i.email_r2_key) ? <EmailOpen item={i} /> : null}
          </li>
        );
      })}
    </ol>
  );
}

interface InboundEmail {
  subject: string | null;
  from_addr: string | null;
  received_at: string;
  text_body: string | null;
  html_body: string | null;
}

/** Plain text of a message: its text part, else its HTML part read as text (never rendered as HTML). */
function emailText(m: InboundEmail): string {
  if (m.text_body && m.text_body.trim()) return m.text_body.trim();
  if (!m.html_body) return '';
  const doc = new DOMParser().parseFromString(m.html_body, 'text/html');
  doc.querySelectorAll('script,style').forEach((n) => n.remove());
  doc.querySelectorAll('br').forEach((n) => n.replaceWith('\n'));
  doc.querySelectorAll('p,div,li,tr,h1,h2,h3,h4,table').forEach((n) => n.append('\n'));
  return (doc.body.textContent ?? '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** An item that came by e-mail with no web page: read it here, or save the original message. */
function EmailOpen({ item }: { item: NewItem }) {
  const [open, setOpen] = useState(false);
  // null = idle, '' = saving, text = why it failed
  const [saving, setSaving] = useState<string | null>(null);
  const mail = useQuery({
    queryKey: ['inbound-email', item.email_id],
    enabled: open && Boolean(item.email_id),
    queryFn: async () =>
      unwrap<InboundEmail | null>(
        await supabase
          .from('inbound_email')
          .select('subject,from_addr,received_at,text_body,html_body')
          .eq('id', item.email_id as string)
          .maybeSingle(),
      ),
  });
  const save = async () => {
    if (!item.email_r2_key) return;
    setSaving('');
    try {
      const name = (item.title_orig || 'e-mail').slice(0, 80).replace(/[\\/:*?"<>|]+/g, ' ').trim();
      await downloadArchived(item.email_r2_key, `${name || 'e-mail'}.eml`);
      setSaving(null);
    } catch (e) {
      setSaving(errorMessage(e));
    }
  };
  return (
    <div className="hz-mail">
      <div className="hz-mail-actions">
        {item.email_id ? (
          <Button size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Close the e-mail' : 'Read the e-mail'}
          </Button>
        ) : null}
        {item.email_r2_key ? (
          <Button size="sm" variant="quiet" busy={saving === ''} onClick={() => void save()}>
            Save the original e-mail
          </Button>
        ) : null}
      </div>
      {saving ? <Notice tone="error">Not saved: {saving}</Notice> : null}
      {open ? (
        mail.isPending ? (
          <Loading label="Opening the e-mail" />
        ) : mail.isError ? (
          <Notice tone="error">The e-mail could not be read: {errorMessage(mail.error)}</Notice>
        ) : mail.data ? (
          <div className="hz-mail-body" lang={item.lang ?? undefined}>
            {emailText(mail.data) || 'This e-mail has no text.'}
          </div>
        ) : (
          <Notice tone="error">The e-mail is no longer in the mailbox.</Notice>
        )
      ) : null}
    </div>
  );
}

type Opened = { sourceId: string; which: 'new' | 'matched' } | null;

/** This week's reading, folded: per source, checks, failures, new and matched items, and the last check.
 *  New and Matched open the items behind them. */
function WeekFigures({
  card,
  week,
  totals,
  filtered,
  lists,
  runsPending,
  isAdmin,
  technical,
  onToggle,
  toggling,
}: Omit<CardShared, 'hz'> & { card: Card; week: NewItem[] }) {
  const [opened, setOpened] = useState<Opened>(null);
  const homepage = new Map(card.regulators.map((r) => [r.id, r.homepage]));
  const labels = sourceLabels(card.sources, card.pages);
  const rows = card.sources.map((s) => {
    const t = totals.get(s.id);
    // label watch and literature have screens of their own: their figures here are the runs' own counts
    const listed = listsItems(s.kind);
    const mine = listed ? week.filter((i) => i.source_id === s.id) : [];
    return {
      s,
      t,
      listed,
      mine,
      fresh: listed ? mine.length : (t?.fresh ?? 0),
      matched: listed ? mine.filter((i) => i.matched).length : (t?.matched ?? 0),
    };
  });
  const sum = rows.reduce(
    (a, r) => ({
      checks: a.checks + (r.t?.runs ?? 0),
      failed: a.failed + (r.t?.failed ?? 0),
      fresh: a.fresh + r.fresh,
      matched: a.matched + r.matched,
    }),
    { checks: 0, failed: 0, fresh: 0, matched: 0 },
  );
  const openRow = opened ? rows.find((r) => r.s.id === opened.sourceId) : undefined;
  const openItems = openRow ? (opened?.which === 'matched' ? openRow.mine.filter((i) => i.matched) : openRow.mine) : [];

  const figButton = (id: string, which: 'new' | 'matched', n: number) => {
    const pressed = opened?.sourceId === id && opened.which === which;
    return (
      <button
        type="button"
        className="hz-fig-btn"
        aria-pressed={pressed}
        title={which === 'matched' ? 'Show the matched items' : 'Show the new items'}
        onClick={() => setOpened(pressed ? null : { sourceId: id, which })}
      >
        {formatNumber(n)}
      </button>
    );
  };

  if (rows.length === 0) {
    return <p className="hz-nothing">The app reads none of these pages yet.</p>;
  }

  return (
    <details className="hz-week">
      <summary>
        <span className="hz-new-title">This week's reading</span>
        <span className="hz-week-sum">
          {runsPending ? '…' : `${formatNumber(sum.checks)} ${sum.checks === 1 ? 'check' : 'checks'}`}
          {sum.failed ? ` · ${formatNumber(sum.failed)} failed` : ''} · {formatNumber(sum.fresh)} new ·{' '}
          {formatNumber(sum.matched)} matched
        </span>
      </summary>
      <ul className="hz-runs">
        {rows.map(({ s, t, listed, fresh, matched }) => {
          const page = sourcePage(s, homepage.get(s.regulator_id));
          const href = safeHref(page);
          const label = labels.get(s.id) ?? s.id;
          const why = offReason(s);
          const waitingSince = waitingForMail(s);
          const lastChecked = t?.lastRun ?? s.last_ok_at;
          const left = filtered.get(s.id);
          const list = s.enabled ? listLine(lists.get(s.id)) : null;
          return (
            <li key={s.id} className={cx('hz-run', !s.enabled && 'is-off')}>
              <div className="hz-run-name">
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {label}
                  </a>
                ) : (
                  <span>{label}</span>
                )}
                {s.origin === 'user' ? <Tag tone="quiet">Added by hand</Tag> : null}
                {!s.enabled ? <Tag tone="quiet">Switched off</Tag> : null}
                {s.enabled && NEEDS_A_LOOK.includes(s.health) ? <HealthMark health={s.health} /> : null}
                {waitingSince ? (
                  <Tag tone="quiet">
                    Waiting for the first e-mail{formatDate(waitingSince) ? ` since ${formatDate(waitingSince)}` : ''}
                  </Tag>
                ) : null}
              </div>
              <div className="hz-run-side">
                <dl className="hz-figs">
                  <div>
                    <dt>Checks</dt>
                    <dd>{t ? formatNumber(t.runs) : runsPending ? '…' : '0'}</dd>
                  </div>
                  <div className={t?.failed ? 'is-failed' : undefined}>
                    <dt>Failed</dt>
                    <dd>{formatNumber(t?.failed ?? 0)}</dd>
                  </div>
                  <div>
                    <dt>New</dt>
                    <dd>{listed && fresh > 0 ? figButton(s.id, 'new', fresh) : formatNumber(fresh)}</dd>
                  </div>
                  <div className={matched ? 'is-hit' : undefined}>
                    <dt>Matched</dt>
                    <dd>{listed && matched > 0 ? figButton(s.id, 'matched', matched) : formatNumber(matched)}</dd>
                  </div>
                  <div>
                    <dt>Last checked</dt>
                    <dd title={formatDateTime(lastChecked)}>{timeAgo(lastChecked)}</dd>
                  </div>
                </dl>
                {isAdmin ? (
                  <Toggle
                    checked={s.enabled}
                    disabled={toggling}
                    onChange={(v) => onToggle(s.id, v)}
                    label={s.enabled ? 'Read' : 'Off'}
                  />
                ) : null}
              </div>
              {why ? <p className="hz-why">{why}</p> : null}
              {list && (list.needsLook || technical) ? (
                <p className={cx('hz-why', list.needsLook && 'is-attention')}>{list.text}</p>
              ) : null}
              {technical ? (
                <p className="hz-tech">
                  {CHANNEL_LABEL[s.channel]} · {s.parser} · {SCHEDULE_LABEL[s.schedule]} · {HEALTH_LABEL[s.health].label}
                  {s.consecutive_failures > 0 ? ` · ${s.consecutive_failures} failed in a row` : ''} · reads {s.url}
                  {t?.lastError ? ` · last note: ${t.lastError}` : ''}
                  {left
                    ? ` · left out by its filters: ${formatNumber(left.count)}, latest “${left.latest.title}” (${left.latest.reason})`
                    : ''}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {openRow ? (
        <div className="hz-opened">
          <div className="hz-opened-head">
            <span>
              {opened?.which === 'matched' ? 'Matched this week' : 'New this week'}: {labels.get(openRow.s.id)}
            </span>
            <Button size="sm" variant="quiet" onClick={() => setOpened(null)}>
              Close
            </Button>
          </div>
          <ItemList items={openItems} showAuthority={card.regulators.length > 1} />
        </div>
      ) : null}
    </details>
  );
}
