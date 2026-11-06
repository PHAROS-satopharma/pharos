import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import '../../styles/screen.css';
import { errorMessage } from '../../lib/api';
import { formatDate, formatDateTime, formatNumber } from '../../lib/format';
import { DOC_TYPE_LABEL, languageName } from '../../lib/labels';
import { safeHref } from '../../lib/safeHref';
import { Button } from '../../ui/Button';
import { Country } from '../../ui/Flag';
import { Input } from '../../ui/Input';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import { cx } from '../../ui/cx';
import { listsItems, offReason, pageStatus, sourceLabels, type PageKind } from '../sources/horizontal';
import { useLiteratureSearch } from '../literature/useLiteratureSearch';
import { answerText, countryAnswers, readsText, summaryLine, toCheckByHand, type CountryAnswer } from './answers';
import { DecisionButtons } from './DecisionButtons';
import { PAPER_PAGE, screenKey, useIngredientScreen, useMorePapers } from './queries';
import { PRESETS, cairoDayOf, presetDays, rangeError, rangeFromSearch, rangeLabel, type DayRange } from './range';
import { ReadEmail } from './ReadEmail';
import type { IngredientScreenData, Mention, Paper, ScreenIngredient, ScreenLiterature } from './types';

const PAGE_KIND: Record<PageKind, string> = {
  database: 'Drug database',
  dhpc: 'DHPC',
  safety: 'Safety notifications',
};

const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`;

/** One active ingredient across every source, for the days she chooses (/ingredients/:id?from=&to=). */
export function IngredientScreen() {
  const { id } = useParams();
  const [search, setSearch] = useSearchParams();
  // One Cairo day per visit, so the presets do not move under her while she reads.
  const [today] = useState(() => cairoDayOf(new Date()));
  const range = rangeFromSearch(search, today);
  const screen = useIngredientScreen(id, range.from, range.to, true);
  const key = screenKey(id ?? '', range.from, range.to);
  const setRange = (from: string, to: string) => setSearch({ from, to });
  const ing = screen.data?.ingredient;

  return (
    <div className="page scr">
      <PageHead
        eyebrow="Ingredient"
        title={ing?.inn_en ?? 'Ingredient'}
        lede={ing ? <IngredientLine ing={ing} /> : 'Every source, one ingredient: where it was mentioned in the days you choose.'}
        actions={
          <Link to="/ingredients" className="btn btn-secondary">
            All ingredients
          </Link>
        }
      />

      <RangeBar range={range} today={today} onChange={setRange} />

      {screen.isPending ? (
        <Loading label="Reading every source" />
      ) : screen.isError ? (
        <ErrorNote title="This ingredient could not be screened." error={screen.error} onRetry={() => void screen.refetch()} />
      ) : (
        <Body data={screen.data} queryKey={key} from={range.from} to={range.to} />
      )}
    </div>
  );
}

function IngredientLine({ ing }: { ing: ScreenIngredient }) {
  const parts = [
    ing.atc_code ? `ATC ${ing.atc_code}` : 'No ATC code',
    ing.classes.length ? ing.classes.map((c) => c.name_en).join(', ') : null,
    `Looked for by ${plural(ing.names, 'name', 'names')} in ${plural(ing.name_languages, 'language', 'languages')}` +
      (ing.class_words
        ? ` and ${plural(ing.class_words, 'class word', 'class words')} in ${plural(ing.class_languages, 'language', 'languages')}`
        : ''),
  ].filter(Boolean);
  return <>{parts.join(' · ')}</>;
}

// ───────────────────────────── the days ─────────────────────────────

function RangeBar({ range, today, onChange }: { range: DayRange; today: string; onChange: (from: string, to: string) => void }) {
  return (
    <div className="scr-range" role="region" aria-label="The days on screen">
      <div className="scr-presets" role="group" aria-label="Choose the days">
        {PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            className={cx('scr-preset', range.preset === p.key && 'is-on')}
            aria-pressed={range.preset === p.key}
            onClick={() => {
              const d = presetDays(p.key, today);
              onChange(d.from, d.to);
            }}
          >
            {p.label}
          </button>
        ))}
      </div>
      <CustomDays key={`${range.from}|${range.to}`} range={range} onChange={onChange} />
      <p className="scr-range-label">
        <strong>{rangeLabel(range.from, range.to)}</strong> · Cairo days, both included
      </p>
    </div>
  );
}

function CustomDays({ range, onChange }: { range: DayRange; onChange: (from: string, to: string) => void }) {
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const problem = rangeError(from, to);
  const changed = from !== range.from || to !== range.to;
  return (
    <form
      className={cx('scr-custom', range.preset === 'custom' && 'is-on')}
      onSubmit={(e) => {
        e.preventDefault();
        if (!problem && changed) onChange(from, to);
      }}
    >
      <label className="scr-day">
        <span className="micro">From</span>
        <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
      </label>
      <label className="scr-day">
        <span className="micro">To</span>
        <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} required />
      </label>
      <Button type="submit" disabled={Boolean(problem) || !changed}>
        Show these days
      </Button>
      {problem && changed ? (
        <p className="scr-range-problem" role="alert">
          {problem}
        </p>
      ) : null}
    </form>
  );
}

// ───────────────────────────── the answers ─────────────────────────────

function Body({
  data,
  queryKey,
  from,
  to,
}: {
  data: IngredientScreenData;
  queryKey: readonly unknown[];
  from: string;
  to: string;
}) {
  const { hers, others } = countryAnswers(data.regulators);
  const all = [...hers, ...others];
  return (
    <>
      {!data.ingredient.active ? (
        <Notice tone="info">
          This ingredient is paused: the app does not look for it, so notices published while it is paused are not
          matched until it is watched again.
        </Notice>
      ) : null}

      {all.length ? <p className="scr-summary">{summaryLine(all)}</p> : null}

      {hers.length ? (
        <section className="scr-section" aria-label="Her countries">
          <SectionHead index="01" title="Her countries" aside={`${hers.length}`} />
          <div className="scr-countries">
            {hers.map((c) => (
              <CountryBlock key={c.country} c={c} queryKey={queryKey} />
            ))}
          </div>
        </section>
      ) : null}

      {others.length ? (
        <section className="scr-section" aria-label="Other authorities">
          <SectionHead index="02" title="Other authorities" aside={`${others.length}`} />
          <div className="scr-countries">
            {others.map((c) => (
              <CountryBlock key={c.country} c={c} queryKey={queryKey} />
            ))}
          </div>
        </section>
      ) : null}

      {!all.length ? (
        <Empty title="No authority is read for this screen yet.">
          <p>Add a source on the Sources screen, or her pages, and the answers appear here.</p>
        </Empty>
      ) : null}

      <section className="scr-section" aria-label="Label changes">
        <SectionHead index="03" title="Label changes" aside={`${data.label_changes.length}`} />
        {data.label_changes.length ? (
          <ol className="scr-mentions">
            {data.label_changes.map((m) => (
              <MentionItem key={m.document_id} m={m} showWhere queryKey={queryKey} />
            ))}
          </ol>
        ) : (
          <p className="scr-quiet">No label change of a product with this ingredient in these days.</p>
        )}
      </section>

      <Literature ing={data.ingredient} lit={data.literature} from={from} to={to} />
    </>
  );
}

function CountryBlock({ c, queryKey }: { c: CountryAnswer; queryKey: readonly unknown[] }) {
  const sources = new Map(c.sources.map((s) => [s.id, s]));
  const read = c.sources.filter((s) => listsItems(s.kind));
  const labels = sourceLabels(read, c.pages);
  const check = toCheckByHand(c.answer);
  return (
    <article className={cx('scr-country', `is-${c.answer}`)}>
      <header className="scr-country-head">
        <h3 className="scr-country-name">
          <Country name={c.country} code={c.code} />
        </h3>
        <p className="scr-answer">{answerText(c)}</p>
      </header>
      <p className="scr-reads">
        {c.regulators.map((r) => r.name).join(' · ')} — {readsText(c)}
      </p>

      {c.mentions.length ? (
        <ol className="scr-mentions">
          {c.mentions.map((m) => (
            <MentionItem key={m.document_id} m={m} showWhere={c.regulators.length > 1} queryKey={queryKey} />
          ))}
        </ol>
      ) : null}

      {c.pages.length || read.length ? (
        <details className="scr-more" open={check}>
          <summary>{c.pages.length ? `Her pages (${c.pages.length}) and what the app reads` : 'What the app reads'}</summary>
          {c.pages.length ? (
            <ul className="scr-pages">
              {c.pages.map((p) => {
                const st = pageStatus(p, sources);
                const href = safeHref(p.url);
                return (
                  <li key={p.id} className={cx('scr-page', `is-${st.state}`)}>
                    {href ? (
                      <a href={href} target="_blank" rel="noopener noreferrer">
                        {p.label}
                      </a>
                    ) : (
                      <span>{p.label}</span>
                    )}
                    <span className="scr-page-kind">{PAGE_KIND[p.kind]}</span>
                    <span className="scr-page-read">{st.label}</span>
                    {st.note ? <span className="scr-note">{st.note}</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
          {read.length ? (
            <ul className="scr-sources">
              {read.map((s) => {
                const why = offReason(s);
                return (
                  <li key={s.id} className={cx('scr-source', !s.enabled && 'is-off')}>
                    <span>{labels.get(s.id)}</span>
                    {!s.enabled ? <span className="scr-page-read">Switched off</span> : null}
                    {why ? <span className="scr-note">{why}</span> : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </details>
      ) : null}
    </article>
  );
}

function MentionItem({ m, showWhere, queryKey }: { m: Mention; showWhere: boolean; queryKey: readonly unknown[] }) {
  const href = safeHref(m.link);
  const sections = Array.isArray(m.sections) ? m.sections.filter((s) => typeof s === 'string') : [];
  return (
    <li className={cx('scr-mention', m.is_backfill && 'is-history')}>
      <div className="scr-meta">
        <span className="scr-date" title={`First seen ${formatDateTime(m.first_seen_at)}`}>
          {m.published_date ? formatDate(m.published_date) : `Found ${formatDate(m.date)}`}
        </span>
        {m.doc_type !== 'other' ? <span>{DOC_TYPE_LABEL[m.doc_type]}</span> : null}
        {showWhere ? <span>{m.regulator_name}</span> : null}
        {m.by_class ? (
          <Tag tone="quiet" title="Only words of its drug class matched, not the ingredient's own names">
            By class
          </Tag>
        ) : null}
        {m.is_backfill ? (
          <Tag tone="quiet" title="Found by a look into the past; it was never alerted">
            History
          </Tag>
        ) : null}
      </div>
      <p className="scr-title" lang={m.lang ?? undefined}>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {m.title}
          </a>
        ) : (
          m.title
        )}
      </p>
      {m.terms.length ? (
        <p className="scr-words">
          <span className="micro">Matched</span>
          {m.terms.map((t) => (
            <span key={`${t.text}|${t.lang ?? ''}`} className="scr-word">
              <span lang={t.lang ?? undefined}>{t.text}</span>
              {t.lang ? <span className="scr-word-lang">{languageName(t.lang)}</span> : null}
            </span>
          ))}
        </p>
      ) : null}
      {sections.length ? <p className="scr-sections">Sections changed: {sections.join(', ')}</p> : null}
      {!href && (m.email_id || m.email_r2_key) ? (
        <ReadEmail emailId={m.email_id} r2Key={m.email_r2_key} title={m.title} lang={m.lang} />
      ) : null}
      <DecisionButtons mention={m} queryKey={queryKey} />
    </li>
  );
}

// ───────────────────────────── the papers ─────────────────────────────

function Literature({ ing, lit, from, to }: { ing: ScreenIngredient; lit: ScreenLiterature; from: string; to: string }) {
  const [more, setMore] = useState(false);
  const [ask, setAsk] = useState(false);
  const extra = useMorePapers(ing.id, from, to, more);
  const live = useLiteratureSearch(ask ? ing.id : null, from, to);
  const papers: Paper[] = [...lit.first, ...(extra.data?.pages.flat() ?? [])];
  const left = lit.papers - papers.length;
  const canMore = left > 0 && (!more || Boolean(extra.hasNextPage));

  return (
    <section className="scr-section" aria-label="Literature">
      <SectionHead index="04" title="Literature" aside={`${lit.papers}`} />
      <p className="scr-lit-line">
        {lit.papers
          ? `${plural(lit.papers, 'paper', 'papers')} in these days: ${formatNumber(lit.by_name)} name the ingredient, ` +
            `${formatNumber(lit.by_class)} only its class · ${formatNumber(lit.pubmed)} in PubMed, ` +
            `${formatNumber(lit.pmc)} in PubMed Central`
          : 'No paper found by the daily literature watch in these days.'}
      </p>

      {lit.by_query.length ? (
        <table className="scr-queries">
          <caption className="micro">What the daily watch searches, and what it found</caption>
          <thead>
            <tr>
              <th scope="col">Search</th>
              <th scope="col">PubMed</th>
              <th scope="col">PubMed Central</th>
            </tr>
          </thead>
          <tbody>
            {lit.by_query.map((q) => (
              <tr key={q.query}>
                <th scope="row">
                  {q.query} <span className="scr-quiet">{q.kind === 'name' ? 'name' : 'class word'}</span>
                </th>
                <td>{formatNumber(q.pubmed)}</td>
                <td>{formatNumber(q.pmc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <div className="scr-live">
        {!ask ? (
          <Button size="sm" onClick={() => setAsk(true)}>
            Count on PubMed and PubMed Central now
          </Button>
        ) : live.isPending ? (
          <Loading label="Asking PubMed and PubMed Central" />
        ) : live.isError ? (
          <Notice tone="error">PubMed and PubMed Central could not be asked: {errorMessage(live.error)}</Notice>
        ) : (
          <ul className="scr-live-list">
            {live.data.queries.map((q) => (
              <li key={q.label}>
                <span className="scr-live-query">{q.label}</span>
                <LiveCount label="PubMed" count={q.pubmed.count} url={q.pubmed.url} error={q.pubmed.error} />
                <LiveCount label="PubMed Central" count={q.pmc.count} url={q.pmc.url} error={q.pmc.error} />
              </li>
            ))}
            <li className="scr-quiet">Counted by publication date, as the two websites count them.</li>
          </ul>
        )}
      </div>

      {papers.length ? (
        <ol className="scr-papers">
          {papers.map((p) => (
            <PaperItem key={p.document_id} p={p} />
          ))}
        </ol>
      ) : null}
      {canMore ? (
        <Button
          className="scr-show-more"
          busy={extra.isFetching}
          onClick={() => (more ? void extra.fetchNextPage() : setMore(true))}
        >
          Show {Math.min(left, PAPER_PAGE)} more of {formatNumber(left)}
        </Button>
      ) : null}
      {extra.isError ? <Notice tone="error">More papers could not be loaded: {errorMessage(extra.error)}</Notice> : null}
    </section>
  );
}

function LiveCount({ label, count, url, error }: { label: string; count: number | null; url: string; error?: string }) {
  const href = safeHref(url);
  const text = count === null ? `${label}: no answer${error ? ` (${error})` : ''}` : `${label}: ${formatNumber(count)}`;
  return href ? (
    <a className="scr-live-count" href={href} target="_blank" rel="noopener noreferrer">
      {text}
    </a>
  ) : (
    <span className="scr-live-count">{text}</span>
  );
}

function PaperItem({ p }: { p: Paper }) {
  const pubmed = safeHref(p.pubmed_url);
  const pmc = safeHref(p.pmc_url);
  return (
    <li className={cx('scr-paper', p.is_backfill && 'is-history')}>
      <div className="scr-meta">
        <span className="scr-date">{formatDate(p.day)}</span>
        {p.journal ? <span>{p.journal}</span> : null}
        {p.by_class ? (
          <Tag tone="quiet" title="Found by a word of its drug class, not by the ingredient's name">
            By class
          </Tag>
        ) : null}
        {p.is_backfill ? (
          <Tag tone="quiet" title="Found by the first look back; it was never alerted">
            History
          </Tag>
        ) : null}
      </div>
      <p className="scr-title" lang={p.lang ?? undefined}>
        {p.title}
      </p>
      {pubmed || pmc ? (
        <p className="scr-paper-links">
          {pubmed ? (
            <a href={pubmed} target="_blank" rel="noopener noreferrer">
              PubMed
            </a>
          ) : null}
          {pmc ? (
            <a href={pmc} target="_blank" rel="noopener noreferrer">
              PubMed Central
            </a>
          ) : null}
        </p>
      ) : null}
    </li>
  );
}
