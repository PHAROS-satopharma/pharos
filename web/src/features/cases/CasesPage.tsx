import { useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import '../../styles/cases.css';
import { errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDate } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { ProductPick, type PickState } from '../products/ProductPick';
import { MeddraPanel } from './Meddra';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import {
  ACCEPT,
  MAX_BYTES,
  MISSING_LABEL,
  ORIGIN_LABEL,
  STATUS_LABEL,
  addDays,
  clockLine,
  isOpen,
  toBase64,
  type CaseOrigin,
  type CaseStatus,
} from './caseForm';

export interface CaseRow {
  id: string;
  ref: string;
  origin: CaseOrigin;
  status: CaseStatus;
  ingredient_id: string | null;
  ingredient: string | null;
  file_name: string | null;
  day_zero: string;
  serious: boolean | null;
  due: string;
  overdue: boolean;
  sent_on: string | null;
  authority_ref: string | null;
  patient: string | null;
  reactions: string | null;
  missing: string[];
  e2b_status: string | null;
  created_at: string;
  updated_at: string;
  /** The product and its strength (0099), e.g. "Carvexa 6.25 mg / 5 mg"; null for a case of one ingredient. */
  product_id: string | null;
  product_strength_id: string | null;
  product: string | null;
}

export const CASES_KEY = ['cases'] as const;

export function useIngredients() {
  return useQuery({
    queryKey: ['cases', 'ingredients'],
    queryFn: async () =>
      unwrap<{ id: string; inn_en: string }[]>(
        await supabase.from('ingredient').select('id, inn_en').eq('active', true).order('inn_en'),
      ),
    staleTime: 5 * 60 * 1000,
  });
}

/** Sends a document to the case-intake function: archived, then read within minutes. */
function NewCase() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const today = cairoToday();
  const [dayZero, setDayZero] = useState(today);
  const [pick, setPick] = useState<PickState>({ product: null, strength: null, ingredient: null });
  const [file, setFile] = useState<File | null>(null);
  const ingredients = useIngredients();

  const send = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose the document first.');
      if (file.size > MAX_BYTES) throw new Error('A case document is at most 10 MB.');
      const data = toBase64(new Uint8Array(await file.arrayBuffer()));
      return invoke<{ case_id: string; dispatched: boolean }>('case-intake', {
        action: 'upload',
        file_name: file.name,
        data,
        day_zero: dayZero,
        ingredient_id: pick.product ? null : pick.ingredient,
        product_id: pick.product,
        strength_id: pick.product ? pick.strength : null,
      });
    },
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: CASES_KEY });
      navigate(`/cases/${r.case_id}`);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    send.mutate();
  }

  return (
    <form className="case-new" onSubmit={submit}>
      <p className="case-hint">
        Drop the report as it arrived: a PDF, a photo of a form, a Word file, a saved email or a text file. PHAROS
        keeps the original and fills in the case form within a few minutes; you check it against the document and
        confirm. A report can also be forwarded to the PHAROS mailbox with CASE in the subject.
      </p>
      <div className="form-grid case-new-grid">
        <Field label="Document" hint="PDF, photo, Word, saved email or text; at most 10 MB">
          <Input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        </Field>
        <Field label="Day zero" hint="The day the company first received the report">
          <Input
            type="date"
            value={dayZero}
            min={addDays(today, -366)}
            max={today}
            onChange={(e) => setDayZero(e.target.value)}
            required
          />
        </Field>
        <ProductPick
          value={pick}
          ingredients={ingredients.data ?? []}
          onChange={(next) => setPick(next)}
          placeholder="PHAROS will suggest it"
        />
      </div>
      <div className="case-actions">
        <Button type="submit" variant="primary" busy={send.isPending} disabled={!file}>
          Open the case
        </Button>
      </div>
      {send.isError ? <Notice tone="error">{errorMessage(send.error)}</Notice> : null}
    </form>
  );
}

function statusTag(row: CaseRow) {
  const tone =
    row.status === 'failed' || (row.overdue && isOpen(row.status))
      ? 'danger'
      : row.status === 'to_confirm'
        ? 'warning'
        : row.status === 'sent'
          ? 'success'
          : row.status === 'not_valid'
            ? 'quiet'
            : 'neutral';
  return <Tag tone={tone}>{STATUS_LABEL[row.status]}</Tag>;
}

export function CasesPage() {
  const { canReview, isAdmin } = useAuth();
  const today = cairoToday();
  const [show, setShow] = useState<'open' | 'all'>('open');
  const cases = useQuery({
    queryKey: CASES_KEY,
    queryFn: async () =>
      unwrap<CaseRow[]>(await supabase.from('v_case_table').select('*').order('created_at', { ascending: false })),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((c) => c.status === 'queued' || c.status === 'reading') ? 15000 : false,
  });
  const rows = (cases.data ?? []).filter((c) => show === 'all' || isOpen(c.status));

  return (
    <div className="page cases-page">
      <PageHead
        eyebrow="Pharmacovigilance"
        title="Cases"
        lede="Individual case safety reports: the source document, the case form PHAROS fills from it, your check and confirmation, the clock to the authority, and the E2B(R3) file."
      />
      {canReview ? (
        <section className="panel">
          <SectionHead index="01" title="New case" />
          <NewCase />
        </section>
      ) : null}
      <section className="panel">
        <SectionHead
          index={canReview ? '02' : '01'}
          title="Cases"
          aside={
            <Select
              value={show}
              onChange={(e) => setShow(e.target.value as 'open' | 'all')}
              aria-label="Which cases"
              options={[
                { value: 'open', label: 'Open cases' },
                { value: 'all', label: 'Every case' },
              ]}
            />
          }
        />
        {cases.isPending ? (
          <Loading />
        ) : cases.isError ? (
          <ErrorNote error={cases.error} onRetry={() => cases.refetch()} />
        ) : rows.length === 0 ? (
          <Empty title={show === 'open' ? 'No open case.' : 'No case yet.'}>
            A case opens from an uploaded document, a forwarded email, or a literature paper on an ingredient's page.
          </Empty>
        ) : (
          <Table className="case-table">
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Where it stands</th>
                <th scope="col">Clock</th>
                <th scope="col">Product or ingredient</th>
                <th scope="col">Patient and reaction</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className={c.overdue && isOpen(c.status) ? 'is-overdue' : undefined}>
                  <td>
                    <Link to={`/cases/${c.id}`} className="case-ref">
                      {c.ref}
                    </Link>
                    <span className="case-sub">
                      {ORIGIN_LABEL[c.origin]} · day zero {formatDate(c.day_zero)}
                    </span>
                  </td>
                  <td>
                    {statusTag(c)}
                    {c.missing.length > 0 && c.status === 'to_confirm' ? (
                      <span className="case-sub">Missing {c.missing.map((m) => MISSING_LABEL[m] ?? m).join(', ')}</span>
                    ) : null}
                  </td>
                  <td>
                    <span className="case-clock">{clockLine(c.due, today, isOpen(c.status))}</span>
                    <span className="case-sub">
                      {c.serious === null ? 'Seriousness not decided' : c.serious ? 'Serious' : 'Not serious'}
                    </span>
                  </td>
                  <td>
                    {c.product ?? c.ingredient ?? '—'}
                    {c.product && c.ingredient ? <span className="case-sub">{c.ingredient}</span> : null}
                  </td>
                  <td>
                    {c.patient ?? '—'}
                    {c.reactions ? <span className="case-sub">{c.reactions}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </section>
      {canReview ? (
        <section className="panel">
          <SectionHead index="03" title="MedDRA" />
          <MeddraPanel isAdmin={isAdmin} />
          <p className="code-source">
            Until MedDRA is loaded, a reaction can be named and grouped with the free terminologies (NCI Thesaurus,
            OAE, ICD-11, MeSH): <Link to="/terminology">Terminology</Link>. They are not MedDRA, and the case stays on
            CIOMS I.
          </p>
        </section>
      ) : null}
    </div>
  );
}
