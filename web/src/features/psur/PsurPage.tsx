import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useIngredientList } from '../people/useIngredientList';
import { errorMessage, unwrap } from '../../lib/api';
import { cairoToday, formatCairoDate, formatDate, formatNumber } from '../../lib/format';
import { DOC_TYPE_LABEL, SIGNAL_OUTCOME_LABEL, SIGNAL_STAGE_LABEL } from '../../lib/labels';
import {
  FIRST_DAY,
  downloadPsurWorkbook,
  intervalFor,
  loadPsurData,
  type EurdEntry,
  type PsurData,
  type PsurIssue,
} from '../../lib/psur';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { StatusPill, Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';

function useEurd(ingredientId: string) {
  return useQuery({
    queryKey: ['eurd', ingredientId],
    enabled: !!ingredientId,
    queryFn: async () =>
      unwrap<EurdEntry[] | null>(
        await supabase
          .from('eurd_entry')
          .select(
            'eurd_id,ingredient_id,substance,combination,eurd,frequency,dlp,submission_date,next_dlp,next_submission_date,' +
              'generics_psur_required,procedure,next_procedure,lead_ms,notes,list_version,list_date',
          )
          .eq('ingredient_id', ingredientId)
          .order('combination')
          .order('substance'),
      ) ?? [],
  });
}

function EurdBox({ rows, chosen, onChoose }: { rows: EurdEntry[]; chosen: number | null; onChoose: (r: EurdEntry) => void }) {
  if (rows.length === 0) {
    return (
      <p className="soft">
        This ingredient is not on the EURD list PHAROS last read, so its PSUR dates come from the national authority.
        Choose the period below.
      </p>
    );
  }
  const list = rows[0];
  return (
    <>
      <Table>
        <thead>
          <tr>
            <th scope="col">Substance on the EURD list</th>
            <th scope="col">Frequency</th>
            <th scope="col">Data lock point</th>
            <th scope="col">Submission</th>
            <th scope="col">Generics submit</th>
            <th scope="col">Procedure</th>
            <th scope="col" className="no-print">
              <span className="visually-hidden">Use</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.eurd_id} className={chosen === r.eurd_id ? 'row-chosen' : undefined}>
              <td>
                {r.substance}
                {r.combination ? <span className="cell-sub">Combination</span> : null}
              </td>
              <td>{r.frequency ?? '—'}</td>
              <td>
                {formatDate(r.dlp)}
                {r.next_dlp ? <span className="cell-sub">Next {formatDate(r.next_dlp)}</span> : null}
              </td>
              <td>{formatDate(r.submission_date)}</td>
              <td>
                {r.generics_psur_required === null ? (
                  '—'
                ) : r.generics_psur_required ? (
                  <Tag tone="warning">Yes</Tag>
                ) : (
                  <Tag tone="neutral" title="Generic, well-established-use, homeopathic and herbal products submit PSURs only when a condition of their licence says so.">
                    No
                  </Tag>
                )}
              </td>
              <td className="mono small">
                {r.procedure ?? '—'}
                {r.lead_ms ? <span className="cell-sub">Lead {r.lead_ms}</span> : null}
              </td>
              <td className="no-print">
                {intervalFor(r) ? (
                  <button type="button" className="link-button small" onClick={() => onChoose(r)}>
                    Use this interval
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p className="soft small">
        From EMA’s list {list.list_version}
        {list.list_date ? `, ${formatDate(list.list_date)}` : ''}. PHAROS reads the list every day.
      </p>
    </>
  );
}

function IssueTable({ rows, empty }: { rows: PsurIssue[]; empty: string }) {
  if (rows.length === 0) return <p className="soft">{empty}</p>;
  return (
    <Table>
      <thead>
        <tr>
          <th scope="col">Date</th>
          <th scope="col">Country</th>
          <th scope="col">Notice</th>
          <th scope="col">Type</th>
          <th scope="col">Decision</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((i) => (
          <tr key={i.id}>
            <td>{formatDate(i.first_date)}</td>
            <td>
              {i.anchor_country ?? i.countries?.[0] ?? '—'}
              {i.anchor_regulator ? <span className="cell-sub">{i.anchor_regulator}</span> : null}
            </td>
            <td>
              <Link to={`/issue/${i.id}`} className="title-link" dir="auto" lang={i.lang ?? undefined}>
                {i.title}
              </Link>
              {i.class_only ? <span className="cell-sub">Class-wide notice</span> : null}
            </td>
            <td>{DOC_TYPE_LABEL[i.doc_type] ?? i.doc_type}</td>
            <td>
              <StatusPill status={i.status} />
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Sections({ data, from, to }: { data: PsurData; from: string; to: string }) {
  const read = data.screening.filter((s) => s.runs > 0);
  const failedOnly = read.filter((s) => s.ok_runs === 0);
  return (
    <>
      <section className="section psur-section">
        <SectionHead index="§3" title="Actions taken in the reporting interval for safety reasons" />
        <p className="soft small">
          Safety letters, alerts, recalls, PSUSA outcomes and signals published by regulators for this ingredient, with
          the decision taken on each. Our own actions are added by the author.
        </p>
        <IssueTable rows={data.actions} empty="No regulator action for this ingredient was found in the interval." />
      </section>

      <section className="section psur-section">
        <SectionHead index="§4" title="Changes to reference safety information" />
        <p className="soft small">Label-change notices, and originator labels whose safety sections changed.</p>
        <IssueTable rows={data.labels} empty="No label-change notice was found in the interval." />
        {data.labelChanges.length > 0 ? (
          <Table>
            <thead>
              <tr>
                <th scope="col">Found</th>
                <th scope="col">Originator product</th>
                <th scope="col">Sections changed</th>
              </tr>
            </thead>
            <tbody>
              {data.labelChanges.map((c) => (
                <tr key={c.id}>
                  <td>{formatCairoDate(c.created_at)}</td>
                  <td dir="auto">
                    {c.issue_id ? (
                      <Link to={`/issue/${c.issue_id}`} className="title-link">
                        {c.spc_product?.product_name ?? 'Product'}
                      </Link>
                    ) : (
                      (c.spc_product?.product_name ?? 'Product')
                    )}
                    <span className="cell-sub">
                      {[c.spc_product?.country_code, c.spc_product?.mah].filter(Boolean).join(' · ')}
                    </span>
                  </td>
                  <td className="mono small">{c.sections.join(' ')}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : null}
      </section>

      <section className="section psur-section">
        <SectionHead index="§11" title="Literature" />
        <IssueTable rows={data.literature} empty="No literature notice was found in the interval." />
      </section>

      <section className="section psur-section">
        <SectionHead index="§15–16" title="Signals: status and evaluation" />
        {data.signals.length === 0 ? (
          <p className="soft">No signal for this ingredient was open in the interval.</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <th scope="col">Signal</th>
                <th scope="col">Opened</th>
                <th scope="col">Stage</th>
                <th scope="col">Outcome</th>
                <th scope="col">Notices</th>
              </tr>
            </thead>
            <tbody>
              {data.signals.map((s) => (
                <tr key={s.id}>
                  <td>
                    <Link to={`/signals/${s.id}`} className="title-link">
                      {s.ref}
                    </Link>
                    <span className="cell-sub">{s.title}</span>
                  </td>
                  <td>{formatCairoDate(s.opened_at)}</td>
                  <td>{SIGNAL_STAGE_LABEL[s.stage] ?? s.stage}</td>
                  <td>
                    {s.outcome ? (SIGNAL_OUTCOME_LABEL[s.outcome]?.label ?? s.outcome) : '—'}
                    {s.closed_at ? <span className="cell-sub">Closed {formatCairoDate(s.closed_at)}</span> : null}
                  </td>
                  <td>{s.notices}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>

      <section className="section psur-section">
        <SectionHead index="Annex" title="Screening in the interval" />
        <p className="soft small">
          {from < FIRST_DAY
            ? `PHAROS began screening on ${formatDate(FIRST_DAY)}; from ${formatDate(from)} to the day before, the screening comes from other records. `
            : ''}
          {formatNumber(read.length)} of {formatNumber(data.screening.length)} sources were read between {formatDate(from)} and{' '}
          {formatDate(to)}
          {failedOnly.length > 0 ? `; ${formatNumber(failedOnly.length)} of them could not be read on any try` : ''}.{' '}
          {data.notRelevant.length > 0
            ? `${formatNumber(data.notRelevant.length)} notices for this ingredient were judged not relevant; the Excel file lists them.`
            : ''}
        </p>
        <Table>
          <thead>
            <tr>
              <th scope="col">Country</th>
              <th scope="col">Source</th>
              <th scope="col">Days read</th>
              <th scope="col">Reads</th>
              <th scope="col">Failed</th>
              <th scope="col">Matched</th>
            </tr>
          </thead>
          <tbody>
            {data.screening.map((s) => (
              <tr key={s.source_id}>
                <td>{s.country}</td>
                <td>
                  {s.regulator}
                  <span className="cell-sub mono">{s.source_id}</span>
                </td>
                <td>{formatNumber(s.days_read)}</td>
                <td>{formatNumber(s.runs)}</td>
                <td>{s.failed_runs > 0 ? formatNumber(s.failed_runs) : '—'}</td>
                <td>{formatNumber(s.items_matched)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </section>
    </>
  );
}

export function PsurPage() {
  const ingredients = useIngredientList();
  const [ingredient, setIngredient] = useState('');
  const eurd = useEurd(ingredient);
  const [chosen, setChosen] = useState<number | null>(null);
  const today = cairoToday();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const inn = useMemo(() => (ingredients.data ?? []).find((i) => i.id === ingredient)?.inn_en ?? '', [ingredients.data, ingredient]);

  // A new ingredient starts from its own (single-substance first) EURD interval, or from PHAROS's first day.
  useEffect(() => {
    if (!ingredient || !eurd.data) return;
    const first = eurd.data.find((r) => intervalFor(r));
    const iv = first ? intervalFor(first) : null;
    setChosen(first && iv ? first.eurd_id : null);
    setFrom(iv?.from ?? FIRST_DAY);
    setTo(iv?.to ?? today);
  }, [ingredient, eurd.data, today]);

  const ready = !!ingredient && !!inn && !!from && !!to && to >= from;
  const data = useQuery({
    queryKey: ['psur', ingredient, from, to],
    enabled: ready,
    queryFn: () => loadPsurData(ingredient, inn, from, to),
  });

  async function saveExcel() {
    if (!data.data) return;
    setSaving(true);
    setSaveError(null);
    try {
      await downloadPsurWorkbook(inn, from, to, eurd.data ?? [], data.data);
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page psur-page">
      <PageHead
        eyebrow="Reports"
        title="PSUR builder"
        lede="The sections of a PSUR (PBRER) that PHAROS can fill from its own records, for one ingredient and one reporting interval, with the EURD dates that set it."
        actions={
          data.data ? (
            <div className="button-row">
              <Button onClick={() => window.print()}>Print or save as PDF</Button>
              <Button variant="primary" busy={saving} onClick={() => void saveExcel()}>
                Download Excel
              </Button>
            </div>
          ) : null
        }
      />

      <div className="button-row psur-form no-print">
        <Field label="Ingredient">
          <Select
            value={ingredient}
            onChange={(e) => setIngredient(e.target.value)}
            placeholder="Choose"
            options={(ingredients.data ?? []).map((i) => ({ value: i.id, label: i.inn_en }))}
          />
        </Field>
        <Field label="Interval from">
          <Input type="date" value={from} max={to || undefined} onChange={(e) => { setFrom(e.target.value); setChosen(null); }} disabled={!ingredient} />
        </Field>
        <Field label="Interval to (data lock point)">
          <Input type="date" value={to} min={from || undefined} onChange={(e) => { setTo(e.target.value); setChosen(null); }} disabled={!ingredient} />
        </Field>
      </div>
      {saveError ? <Notice tone="error">The Excel file could not be built: {saveError}</Notice> : null}

      {!ingredient ? (
        <Empty title="Choose an ingredient.">
          <p>The interval comes from EMA’s EURD list when the ingredient is on it; you can change it.</p>
        </Empty>
      ) : (
        <>
          <section className="section psur-section">
            <SectionHead index="EURD" title={`${inn}: PSUR frequency and dates`} />
            {eurd.isPending ? (
              <Loading label="Reading the EURD list" />
            ) : eurd.isError ? (
              <ErrorNote error={eurd.error} onRetry={() => void eurd.refetch()} />
            ) : (
              <EurdBox
                rows={eurd.data}
                chosen={chosen}
                onChoose={(r) => {
                  const iv = intervalFor(r);
                  if (!iv) return;
                  setChosen(r.eurd_id);
                  setFrom(iv.from);
                  setTo(iv.to);
                }}
              />
            )}
            {ready ? (
              <p className="psur-interval">
                Reporting interval: <strong>{formatDate(from)}</strong> to <strong>{formatDate(to)}</strong>
                {to > today ? <span className="soft"> (still running: records up to today)</span> : null}
              </p>
            ) : null}
          </section>

          {!ready ? null : data.isPending ? (
            <Loading label="Gathering the records of the interval" />
          ) : data.isError ? (
            <ErrorNote error={data.error} onRetry={() => void data.refetch()} />
          ) : (
            <Sections data={data.data} from={from} to={to} />
          )}
        </>
      )}
    </div>
  );
}
