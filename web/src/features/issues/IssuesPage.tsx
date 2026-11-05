import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  describeFilters,
  fetchAllIssues,
  useIngredientNames,
  useIssues,
  useStatusCounts,
  type IssueFilters,
} from './queries';
import { useCountryIndex } from '../../lib/regulators';
import { useDebounced } from '../../lib/useDebounced';
import { exportIssues } from '../../lib/excel';
import { errorMessage } from '../../lib/api';
import { safeHref } from '../../lib/safeHref';
import { formatNumber } from '../../lib/format';
import { DOC_TYPE_LABEL, STATUS_LABEL } from '../../lib/labels';
import { DOC_TYPES, ISSUE_STATUSES, type DocType, type IssueRow, type IssueStatus } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { IngredientChips, StatusPill } from '../../ui/Tag';
import { Country } from '../../ui/Flag';
import { DateStamp } from '../../ui/DateStamp';
import { Stat, StatRow } from '../../ui/Stat';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { PageHead } from '../../ui/Text';
import { cx } from '../../ui/cx';

const PAGE = 200;

function readFilters(p: URLSearchParams): IssueFilters {
  const status = p.get('status') ?? '';
  const type = p.get('type') ?? '';
  return {
    country: p.get('country') ?? '',
    ingredient: p.get('ingredient') ?? '',
    status: (ISSUE_STATUSES as string[]).includes(status) ? (status as IssueStatus) : '',
    type: (DOC_TYPES as string[]).includes(type) ? (type as DocType) : '',
    q: p.get('q') ?? '',
    history: p.get('history') === '1',
    classWide: p.get('classwide') === '1',
  };
}

function isFiltered(f: IssueFilters): boolean {
  return Boolean(f.country || f.ingredient || f.status || f.type || f.q.trim() || f.history || f.classWide);
}

function otherCountries(r: IssueRow): string[] {
  const anchor = r.anchor_country ?? r.countries?.[0] ?? null;
  return (r.countries ?? []).filter((c) => c !== anchor);
}

export function IssuesPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => readFilters(params), [params]);
  const [limit, setLimit] = useState(PAGE);
  const [search, setSearch] = useState(filters.q);
  const debouncedSearch = useDebounced(search, 350);
  const [active, setActive] = useState(-1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const navigate = useNavigate();
  const countries = useCountryIndex();
  const ingredients = useIngredientNames();
  const issues = useIssues(filters, limit);
  const counts = useStatusCounts(filters);
  const rows = useMemo(() => issues.data?.rows ?? [], [issues.data]);
  const total = issues.data?.total ?? 0;
  const tableRef = useRef<HTMLTableSectionElement>(null);
  // The list's own address (with its filters) travels to the notification, so its back link returns here.
  const listState = useMemo(() => ({ back: params.toString() ? `/?${params.toString()}` : '/' }), [params]);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setLimit(PAGE);
    setActive(-1);
  }

  useEffect(() => {
    if (debouncedSearch !== filters.q) setParam('q', debouncedSearch);
    // setParam is recreated each render; the search text is the only trigger here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  // j / k move through the rows, Enter opens the one marked.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (e.key === 'j') {
        e.preventDefault();
        setActive((i) => Math.min(rows.length - 1, i + 1));
      } else if (e.key === 'k') {
        e.preventDefault();
        setActive((i) => Math.max(0, i - 1));
      } else if (e.key === 'Enter' && active >= 0 && active < rows.length) {
        if (target?.closest('a, button')) return;
        e.preventDefault();
        navigate(`/issue/${rows[active].id}`, { state: listState });
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, active, navigate, listState]);

  useEffect(() => {
    if (active < 0 || active >= rows.length) return;
    const el = tableRef.current?.querySelector<HTMLElement>(`[data-row="${active}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [active, rows.length]);

  async function onExport() {
    setExporting(true);
    setExportError(null);
    setExportNote(null);
    try {
      const { rows: all, total: matching } = await fetchAllIssues(filters);
      await exportIssues(all, describeFilters(filters), matching);
      if (matching > all.length) {
        setExportNote(
          `Exported the first ${formatNumber(all.length)} of ${formatNumber(matching)} notices. Narrow the filters to export the rest.`,
        );
      }
    } catch (e) {
      setExportError(errorMessage(e));
    } finally {
      setExporting(false);
    }
  }

  function clearFilters() {
    setSearch('');
    setParams(new URLSearchParams(), { replace: true });
    setLimit(PAGE);
  }

  const filtered = isFiltered(filters);

  return (
    <div className="page">
      <PageHead
        eyebrow="Safety notifications"
        title="What the regulators published"
        lede="Newest first. Titles are the originals, exactly as each regulator published them."
        actions={
          <Button onClick={() => void onExport()} busy={exporting} disabled={!rows.length}>
            {exporting ? 'Preparing the file' : 'Export to Excel'}
          </Button>
        }
        foot={
          <StatRow label="Notifications by status: choose one to show only those">
            {ISSUE_STATUSES.map((s) => (
              <Stat
                key={s}
                tone={s}
                label={STATUS_LABEL[s]}
                value={counts.data?.[s]}
                active={filters.status === s}
                title={filters.status === s ? 'Show every status again' : `Show only ${STATUS_LABEL[s].toLowerCase()}`}
                onClick={() => setParam('status', filters.status === s ? '' : s)}
              />
            ))}
          </StatRow>
        }
      />

      <div className="filters" role="search">
        <Field label="Search titles" className="filters-search">
          <Input
            type="search"
            value={search}
            placeholder="Words from the original title"
            onChange={(e) => setSearch(e.target.value)}
          />
        </Field>
        <Field label="Country">
          <Select
            value={filters.country}
            onChange={(e) => setParam('country', e.target.value)}
            placeholder="Every country"
            options={countries.names.map((n) => ({ value: n, label: n }))}
          />
        </Field>
        <Field label="Ingredient">
          <Select
            value={filters.ingredient}
            onChange={(e) => setParam('ingredient', e.target.value)}
            placeholder="Every ingredient"
            options={(ingredients.data ?? []).map((n) => ({ value: n, label: n }))}
          />
        </Field>
        <Field label="Status">
          <Select
            value={filters.status}
            onChange={(e) => setParam('status', e.target.value)}
            placeholder="Any status"
            options={ISSUE_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))}
          />
        </Field>
        <Field label="Type">
          <Select
            value={filters.type}
            onChange={(e) => setParam('type', e.target.value)}
            placeholder="Any type"
            options={DOC_TYPES.map((t) => ({ value: t, label: DOC_TYPE_LABEL[t] }))}
          />
        </Field>
        <div className="filters-toggles">
          <Toggle
            checked={filters.history}
            onChange={(v) => setParam('history', v ? '1' : '')}
            label="Include history (backfill)"
          />
          <Toggle
            checked={filters.classWide}
            onChange={(v) => setParam('classwide', v ? '1' : '')}
            label="Include class-wide notices"
          />
        </div>
      </div>

      <div className="toolbar">
        <span className="toolbar-count">
          {issues.isPending
            ? ' '
            : total === rows.length
              ? `${formatNumber(total)} ${total === 1 ? 'notification' : 'notifications'}`
              : `Showing ${formatNumber(rows.length)} of ${formatNumber(total)}`}
          {issues.isFetching && !issues.isPending ? <span className="soft"> · updating</span> : null}
        </span>
        <span className="toolbar-hint soft">
          <kbd>j</kbd> <kbd>k</kbd> to move, <kbd>Enter</kbd> to open
        </span>
        {filtered ? (
          <button type="button" className="link-button" onClick={clearFilters}>
            Clear filters
          </button>
        ) : null}
      </div>

      {exportError ? <Notice tone="error">The export did not finish: {exportError}</Notice> : null}
      {exportNote ? <Notice tone="info">{exportNote}</Notice> : null}

      {issues.isPending ? (
        <Loading label="Reading the notifications" />
      ) : issues.isError ? (
        <ErrorNote
          title="The notifications could not be loaded."
          error={issues.error}
          onRetry={() => void issues.refetch()}
        />
      ) : rows.length === 0 ? (
        filtered ? (
          <Empty
            title="Nothing matches these filters."
            action={
              <Button onClick={clearFilters} variant="secondary">
                Clear filters
              </Button>
            }
          >
            <p>Try fewer filters, or include the history from before the watch started.</p>
          </Empty>
        ) : (
          <Empty
            title="Nothing new has been found yet."
            action={
              <Button onClick={() => setParam('history', '1')} variant="secondary">
                Show the history
              </Button>
            }
          >
            <p>
              When a regulator publishes a notice that names an ingredient on the watchlist, it appears here within a
              few hours, with a link to the original. Notices published before the watch started are kept as history
              and hidden from this list until you ask for them.
            </p>
          </Empty>
        )
      ) : (
        <>
          <div className="issues-wrap">
            <table className="table issues">
              <thead>
                <tr>
                  <th scope="col" className="col-date">
                    Date
                  </th>
                  <th scope="col" className="col-country">
                    Published by
                  </th>
                  <th scope="col" className="col-ingredient">
                    Ingredient
                  </th>
                  <th scope="col">Safety notification</th>
                  <th scope="col" className="col-status">
                    Status
                  </th>
                  <th scope="col" className="col-link">
                    <span className="visually-hidden">Original</span>
                  </th>
                </tr>
              </thead>
              <tbody ref={tableRef}>
                {rows.map((r, i) => {
                  const others = otherCountries(r);
                  const anchor = r.anchor_country ?? r.countries?.[0] ?? null;
                  return (
                    <tr
                      key={r.id}
                      data-row={i}
                      className={cx('issue-row', i === active && 'is-active', r.status === 'new' && 'is-new')}
                      onClick={() => navigate(`/issue/${r.id}`, { state: listState })}
                    >
                      <td data-label="Date" className="col-date nowrap">
                        <DateStamp value={r.first_date} />
                      </td>
                      <td data-label="Published by" className="col-country">
                        <span className="cell-line">
                          <Country name={anchor} />
                          {others.length > 0 ? (
                            <span className="more" title={`Also published in ${others.join(', ')}`}>
                              +{others.length}
                            </span>
                          ) : null}
                        </span>
                        <span className="cell-sub">{r.anchor_regulator ?? '—'}</span>
                      </td>
                      <td data-label="Ingredient" className="col-ingredient">
                        <IngredientChips ingredients={r.ingredients} classOnly={r.class_only} />
                      </td>
                      <td data-label="Safety notification" className="col-title">
                        <Link
                          to={`/issue/${r.id}`}
                          state={listState}
                          className="title-link"
                          dir="auto"
                          lang={r.lang ?? undefined}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {r.title}
                        </Link>
                        <span className="title-meta">
                          <span>{DOC_TYPE_LABEL[r.doc_type]}</span>
                          {r.is_backfill ? <span className="tag tag-quiet">History</span> : null}
                        </span>
                      </td>
                      <td data-label="Status" className="col-status">
                        <StatusPill status={r.status} />
                      </td>
                      <td data-label="Link" className="col-link">
                        {safeHref(r.link) ? (
                          <a
                            href={safeHref(r.link) ?? undefined}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="open-link"
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Open on the regulator’s site: ${r.title}`}
                            title="Open on the regulator’s site"
                          >
                            <span aria-hidden>↗</span>
                          </a>
                        ) : (
                          <span className="soft">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length < total ? (
            <div className="more-row">
              <Button onClick={() => setLimit((l) => l + PAGE)} busy={issues.isFetching}>
                Show {formatNumber(Math.min(PAGE, total - rows.length))} more
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
