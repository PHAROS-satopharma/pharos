import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { downloadArchived, errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDateTime } from '../../lib/format';
import { personNames } from '../../lib/people';
import type { EurdEntry } from '../../lib/psur';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { useIngredientList } from '../people/useIngredientList';
import { SignOff } from '../signoff/SignOff';
import { FileHash } from './FileHash';
import {
  type PackKind,
  type PackRequest,
  PACK_NAME,
  daysProblem,
  kindOptions,
  lastTwelveMonths,
  newestFirst,
  packFileName,
  packLabel,
  packsFor,
  packsOf,
  psurDays,
  statusText,
  stillWaiting,
} from './packs';
import '../../styles/reports-packs.css';

type Row = PackRequest & { ingredient: { inn_en: string } | null; requester: string };

function usePacks(isAdmin: boolean) {
  return useQuery({
    queryKey: ['report-requests', isAdmin],
    queryFn: async (): Promise<Row[]> => {
      const rows =
        unwrap<(PackRequest & { ingredient: { inn_en: string } | null })[] | null>(
          await supabase
            .from('report_request')
            .select('*, ingredient(inn_en)')
            .order('requested_at', { ascending: false })
            .limit(50),
        ) ?? [];
      // Inspection packs are for administrators only: the database reads them the same way (0048).
      const mine = packsFor(rows, isAdmin);
      const names = await personNames(mine.map((r) => r.requested_by));
      return newestFirst(mine).map((r) => ({ ...r, requester: names.get(r.requested_by) ?? '' }));
    },
    // While a pack is on its way, the list is read again every minute.
    refetchInterval: (q) => (q.state.data && stillWaiting(q.state.data) ? 60_000 : false),
  });
}

/** The form a reviewer or an administrator asks for a pack with: an inspection pack, an administrator only. */
function AskForm({
  isAdmin,
  kind,
  setKind,
  ingredient,
  setIngredient,
}: {
  isAdmin: boolean;
  kind: PackKind;
  setKind: (k: PackKind) => void;
  ingredient: string;
  setIngredient: (id: string) => void;
}) {
  const qc = useQueryClient();
  const today = cairoToday();
  const ingredients = useIngredientList();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [fromEurd, setFromEurd] = useState(false);

  // The EURD rows of the ingredient chosen: the PSUR pack starts from its interval.
  const eurd = useQuery({
    queryKey: ['eurd-entry', ingredient],
    enabled: kind === 'psur' && ingredient !== '',
    queryFn: async () =>
      unwrap<Pick<EurdEntry, 'dlp' | 'frequency' | 'next_dlp'>[] | null>(
        await supabase.from('eurd_entry').select('dlp,frequency,next_dlp').eq('ingredient_id', ingredient).order('eurd_id'),
      ) ?? [],
  });

  useEffect(() => {
    if (kind === 'inspection') {
      const d = lastTwelveMonths(today);
      setFrom(d.from);
      setTo(d.to);
      setFromEurd(false);
    } else if (eurd.data) {
      const d = psurDays(eurd.data, today);
      setFrom(d.from);
      setTo(d.to);
      setFromEurd(d.fromEurd);
    }
  }, [kind, eurd.data, today]);

  const problem = kind === 'psur' && !ingredient ? 'Choose the ingredient.' : daysProblem(from, to, today);
  const ask = useMutation({
    mutationFn: async () =>
      unwrap<string>(
        await supabase.rpc('request_report', {
          p_kind: kind,
          p_ingredient: kind === 'psur' ? ingredient : null,
          p_from: from,
          p_to: to,
        }),
      ),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['report-requests'] });
    },
  });

  const options = useMemo(
    () => (ingredients.data ?? []).map((i) => ({ value: i.id, label: i.inn_en })),
    [ingredients.data],
  );

  return (
    <form
      className="pack-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!problem) ask.mutate();
      }}
    >
      <div className="form-grid">
        <Field label="Pack">
          <Select value={kind} options={kindOptions(isAdmin)} onChange={(e) => setKind(e.target.value as PackKind)} />
        </Field>
        {kind === 'psur' ? (
          <Field label="Ingredient">
            <Select
              value={ingredient}
              options={options}
              placeholder="Choose the ingredient"
              onChange={(e) => setIngredient(e.target.value)}
            />
          </Field>
        ) : null}
        <Field label="First day">
          <Input type="date" value={from} max={today} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="Last day">
          <Input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      <p className="small muted pack-hint">
        {kind === 'psur'
          ? fromEurd
            ? 'The days start at the EURD interval of the ingredient, up to today. Change them if you need other days.'
            : ingredient
              ? 'This ingredient has no EURD interval that has started: the last 12 months. Change them if you need other days.'
              : 'Sections 3, 4, 11 and 15–16 of the PSUR for one ingredient, with the screening annex.'
          : 'Coverage, the screening log, every decision and signature, the reports to the authority, the weekly reports with their SHA-256, the archive checks, the audit log and the people.'}{' '}
        The pack is made by the next collection run, within four hours, and you are told on Telegram. At most five
        years.
      </p>
      {ask.isError ? <Notice tone="error">The pack could not be asked for: {errorMessage(ask.error)}</Notice> : null}
      {ask.isSuccess ? <Notice tone="ok">Asked for. It is listed below until it is made.</Notice> : null}
      <div className="button-row">
        <Button type="submit" variant="primary" busy={ask.isPending} disabled={!!problem || ask.isPending}>
          Ask for the pack
        </Button>
        {problem && (from || to) ? <span className="small muted">{problem}</span> : null}
      </div>
    </form>
  );
}

function PackCard({ r, save }: { r: Row; save: (key: string, filename: string) => Promise<void> }) {
  const ing = r.ingredient?.inn_en ?? null;
  const name = packLabel(r, ing);
  const made = r.status === 'done' && r.pdf_r2_key && r.xlsx_r2_key && r.pdf_sha256 && r.xlsx_sha256;
  return (
    <li className="weekly-card pack-card">
      <div className="weekly-head">
        <span className="report-month">{name}</span>
        <span className="cell-sub">
          Asked for by {r.requester || 'a member of the team'}, <span className="mono">{formatDateTime(r.requested_at)}</span>
        </span>
        <span className={`pack-status pack-status-${r.status}`}>
          {statusText(r)}
          {r.status === 'done' && r.made_at ? (
            <>
              {' '}
              <span className="mono">{formatDateTime(r.made_at)}</span>
            </>
          ) : null}
        </span>
      </div>
      {made ? (
        <>
          <div className="evidence-files">
            <div className="evidence-file">
              <Button
                className="evidence-download"
                onClick={() => void save(r.pdf_r2_key as string, packFileName(r, ing, 'pdf'))}
                aria-label={`Download the ${name} as PDF`}
              >
                PDF
              </Button>
              <FileHash hash={r.pdf_sha256 as string} what={`PDF of the ${name}`} />
            </div>
            <div className="evidence-file">
              <Button
                className="evidence-download"
                onClick={() => void save(r.xlsx_r2_key as string, packFileName(r, ing, 'xlsx'))}
                aria-label={`Download the ${name} as Excel`}
              >
                Excel
              </Button>
              <FileHash hash={r.xlsx_sha256 as string} what={`Excel file of the ${name}`} />
            </div>
          </div>
          <SignOff kind="pack" id={r.id} name={name} />
        </>
      ) : null}
    </li>
  );
}

/** Packs on request: the form (reviewers and administrators) and every pack asked for, newest first. The
 *  ingredient chosen in the form narrows the list to its packs. */
export function Packs() {
  const { canReview, isAdmin } = useAuth();
  const packs = usePacks(isAdmin);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<PackKind>('psur');
  const [ingredient, setIngredient] = useState('');
  const ingredients = useIngredientList();
  const only = canReview && kind === 'psur' ? ingredient : '';
  const onlyName = (ingredients.data ?? []).find((i) => i.id === only)?.inn_en ?? '';
  const shown = useMemo(() => packsOf(packs.data ?? [], only), [packs.data, only]);

  async function save(key: string, filename: string) {
    setError(null);
    try {
      await downloadArchived(key, filename);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      {canReview ? (
        <AskForm isAdmin={isAdmin} kind={kind} setKind={setKind} ingredient={ingredient} setIngredient={setIngredient} />
      ) : null}
      {error ? <Notice tone="error">The file could not be downloaded: {error}</Notice> : null}
      {packs.isPending ? (
        <Loading label="Reading the packs" />
      ) : packs.isError ? (
        <ErrorNote error={packs.error} onRetry={() => void packs.refetch()} />
      ) : packs.data.length === 0 ? (
        <Empty title="No pack asked for yet.">
          <p>
            A {PACK_NAME.psur} gathers what PHAROS found for one ingredient over its PSUR interval
            {isAdmin ? `; an ${PACK_NAME.inspection.toLowerCase()} gathers the evidence an inspector asks for` : ''}.
          </p>
        </Empty>
      ) : shown.length === 0 ? (
        <Empty title={`No pack for ${onlyName || 'this ingredient'} yet.`}>
          <p>Ask for one above, or choose another ingredient.</p>
        </Empty>
      ) : (
        <>
          {only ? (
            <p className="small muted pack-shown">
              The packs for {onlyName || 'this ingredient'}: {shown.length} of {packs.data.length}.
            </p>
          ) : null}
          <ul className="weekly-list pack-list">
            {shown.map((r) => (
              <PackCard key={r.id} r={r} save={save} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}
