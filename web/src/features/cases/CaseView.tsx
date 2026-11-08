import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import '../../styles/cases.css';
import { archiveUrl, errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDate, formatDateTime } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import { CASES_KEY, useIngredients } from './CasesPage';
import {
  ACTION,
  AGE_GROUP,
  AGE_UNIT,
  CRITERIA,
  MISSING_LABEL,
  ORIGIN_LABEL,
  OUTCOME,
  QUALIFICATION,
  REPORT_TYPE,
  ROLE,
  SEX,
  STATUS_LABEL,
  STEP_LABEL,
  caseDue,
  caseMissing,
  clockLine,
  e2bProblems,
  isOpen,
  numberOrNull,
  orNull,
  type CaseForm,
  type CaseOrigin,
  type CaseStatus,
  type CaseStep,
  type Evidence,
  type Product,
  type Reaction,
  type CaseCoding,
  type DrugSuggestion,
  suggestionsFor,
} from './caseForm';
import { ciomsHtml, ciomsProblems } from './cioms';
import { CodingSource, DrugCoding, MeshCoding } from './Coding';
import { Listed } from './Listed';
import { ProductPick, pickedProduct, type PickState } from '../products/ProductPick';
import { UNITS, suspectLine, withSuspect } from '../products/productForm';
import { useProducts } from '../products/useProducts';

interface CaseRecord {
  id: string;
  ref: string;
  origin: CaseOrigin;
  status: CaseStatus;
  ingredient_id: string | null;
  product_id: string | null;
  product_strength_id: string | null;
  document_id: string | null;
  file_name: string | null;
  mime: string | null;
  sha256: string | null;
  r2_key: string | null;
  day_zero: string;
  serious: boolean | null;
  extracted: { serious?: string; is_case?: boolean; evidence?: Evidence[]; missing?: string[]; notes?: string } | null;
  data: CaseForm | null;
  reader_model: string | null;
  read_at: string | null;
  read_error: string | null;
  sent_on: string | null;
  authority_ref: string | null;
  e2b_status: 'queued' | 'made' | 'failed' | null;
  e2b_error: string | null;
  e2b_r2_key: string | null;
  e2b_sha256: string | null;
  e2b_at: string | null;
  updated_at: string;
  document: { url: string | null; title_orig: string | null } | null;
  coding: CaseCoding | null;
  coding_status: 'queued' | 'done' | 'failed' | null;
  coding_error: string | null;
  coded_at: string | null;
}

interface CaseEvent {
  id: string;
  step: CaseStep;
  comment: string | null;
  created_at: string;
  person: { full_name: string } | null;
}

function useCase(id: string) {
  return useQuery({
    queryKey: [...CASES_KEY, id],
    queryFn: async () =>
      unwrap<CaseRecord>(
        await supabase
          .from('safety_case')
          .select('*, document:document_id(url, title_orig)')
          .eq('id', id)
          .single(),
      ),
    refetchInterval: (q) => {
      const c = q.state.data;
      return c && (c.status === 'queued' || c.status === 'reading' || c.e2b_status === 'queued' || c.coding_status === 'queued')
        ? 10000
        : false;
    },
  });
}

function useEvents(id: string, updatedAt: string | undefined) {
  return useQuery({
    queryKey: [...CASES_KEY, id, 'events', updatedAt],
    queryFn: async () =>
      unwrap<CaseEvent[]>(
        await supabase
          .from('case_event')
          .select('id, step, comment, created_at, person:person_id(full_name)')
          .eq('case_id', id)
          .order('created_at', { ascending: true }),
      ),
    enabled: Boolean(updatedAt),
  });
}

/** Opens a page made here (the CIOMS I form) in a new tab, from which it is printed or saved as PDF. */
function openPage(html: string) {
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
  window.open(url, '_blank', 'noopener,noreferrer');
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function openArchived(key: string) {
  const url = await archiveUrl(key);
  window.open(url, '_blank', 'noopener,noreferrer');
}

function TextField({
  label,
  value,
  onChange,
  disabled,
  type = 'text',
  hint,
}: {
  label: string;
  value: string | number | null | undefined;
  onChange: (v: string) => void;
  disabled: boolean;
  type?: string;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <Input type={type} value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled} />
    </Field>
  );
}

/** A number field that keeps what is being typed ("6." on the way to 6.25) and stores the number. */
function AmountField({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState(value == null ? '' : String(value));
  useEffect(() => {
    if (numberOrNull(text) !== (value ?? null)) setText(value == null ? '' : String(value));
  }, [value, text]);
  return (
    <TextField
      label={label}
      value={text}
      onChange={(v) => {
        setText(v);
        onChange(numberOrNull(v));
      }}
      disabled={disabled}
    />
  );
}

function Choice({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string | null | undefined;
  options: { value: string; label: string }[];
  onChange: (v: string | null) => void;
  disabled: boolean;
}) {
  return (
    <Field label={label}>
      <Select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        placeholder="Not stated"
        options={options}
        disabled={disabled}
      />
    </Field>
  );
}

function Group({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <fieldset className="case-group">
      <legend className="case-group-title">
        {title}
        {aside ? <span className="case-group-aside">{aside}</span> : null}
      </legend>
      {children}
    </fieldset>
  );
}

/** What the document says behind the fields of one part of the form. */
function Quotes({ evidence, prefix }: { evidence: Evidence[]; prefix: string }) {
  const mine = evidence.filter((e) => e.field === prefix || e.field.startsWith(`${prefix}.`) || e.field.startsWith(`${prefix}[`));
  if (mine.length === 0) return null;
  return (
    <ul className="case-quotes">
      {mine.map((e, i) => (
        <li key={i}>
          <q>{e.quote}</q>
          <span className="case-sub">
            {e.field}
            {e.page ? ` · page ${e.page}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function CaseView() {
  const { id = '' } = useParams();
  const qc = useQueryClient();
  const { canReview } = useAuth();
  const today = cairoToday();
  const c = useCase(id);
  const events = useEvents(id, c.data?.updated_at);
  const ingredients = useIngredients();
  const productList = useProducts();

  const [draft, setDraft] = useState<CaseForm>({});
  const [serious, setSerious] = useState<boolean | null>(null);
  const [pick, setPick] = useState<PickState>({ product: null, strength: null, ingredient: null });
  const [dirty, setDirty] = useState(false);
  const [comment, setComment] = useState('');
  const [sentOn, setSentOn] = useState(today);
  const [authorityRef, setAuthorityRef] = useState('');
  const [newDayZero, setNewDayZero] = useState('');
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const record = c.data;
  useEffect(() => {
    if (!record || dirty) return;
    setDraft(record.data ?? {});
    setSerious(record.serious);
    setPick({ product: record.product_id, strength: record.product_strength_id, ingredient: record.ingredient_id });
  }, [record, dirty]);

  const act = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: async () => {
      setDirty(false);
      setComment('');
      await qc.invalidateQueries({ queryKey: CASES_KEY });
    },
    onError: (e) => setMessage({ tone: 'error', text: errorMessage(e) }),
  });

  if (c.isPending) return <Loading />;
  if (c.isError || !record) {
    return (
      <div className="page">
        <ErrorNote error={c.error} onRetry={() => c.refetch()} />
      </div>
    );
  }

  const status = record.status;
  const editable = canReview && (status === 'to_confirm' || status === 'failed' || status === 'confirmed');
  const evidence = record.extracted?.evidence ?? [];
  const missing = caseMissing(draft);
  const due = caseDue(record.day_zero, serious);
  const e2bIssues = e2bProblems(draft, serious, status);
  const ciomsIssues = ciomsProblems(draft, serious, status);
  const seen = record.updated_at;
  const busy = act.isPending;

  const edit = (next: CaseForm) => {
    setDraft(next);
    setDirty(true);
    setMessage(null);
  };
  const patient = draft.patient ?? {};
  const reporter = draft.reporter ?? {};
  const products = draft.products ?? [];
  const reactions = draft.reactions ?? [];
  const setPatient = (k: string, v: unknown) => edit({ ...draft, patient: { ...patient, [k]: v } });
  const setReporter = (k: string, v: unknown) => edit({ ...draft, reporter: { ...reporter, [k]: v } });
  const setProduct = (i: number, k: keyof Product, v: unknown) =>
    edit({ ...draft, products: products.map((p, j) => (j === i ? { ...p, [k]: v } : p)) });
  const setIngredientLine = (i: number, k: number, field: 'name' | 'amount' | 'unit', v: unknown) =>
    setProduct(
      i,
      'ingredients',
      (products[i].ingredients ?? []).map((x, j) => (j === k ? { ...x, [field]: v } : x)),
    );
  // The ingredients whose label a coded reaction is checked against: the case's own, else each of its product's.
  const picked = pickedProduct(productList.data, pick);
  const listedFor: { id: string; who: string | null }[] = pick.ingredient
    ? [{ id: pick.ingredient, who: null }]
    : (picked.product?.ingredients ?? []).map((x) => ({ id: x.id, who: x.inn_en }));
  const setReaction = (i: number, k: keyof Reaction, v: unknown) =>
    edit({ ...draft, reactions: reactions.map((r, j) => (j === i ? { ...r, [k]: v } : r)) });

  const coding = record.coding;
  const historyCodes = patient.history_codes ?? [];
  const chooseDrug = (i: number, d: DrugSuggestion | null) =>
    edit({
      ...draft,
      products: products.map((p, j) =>
        j === i
          ? {
              ...p,
              rxcui: d ? d.rxcui || null : null,
              rxnorm_name: d ? d.name : null,
              unii: d ? d.ingredients.map((x) => x.unii).filter(Boolean).join(', ') || null : null,
            }
          : p,
      ),
    });

  const rpc = (name: string, args: Record<string, unknown>, done: string) =>
    act.mutate(async () => {
      unwrap(await supabase.rpc(name, args));
      setMessage({ tone: 'ok', text: done });
    });
  const ask = (action: 'read' | 'e2b' | 'code', done: string) =>
    act.mutate(async () => {
      const r = await invoke<{ dispatched: boolean }>('case-intake', { action, case_id: record.id, seen });
      setMessage({
        tone: 'ok',
        text: r.dispatched ? done : `${done} GitHub could not be reached; the next run (within four hours) does it.`,
      });
    });
  const formArgs = {
    p_case: record.id,
    p_seen: seen,
    p_data: draft,
    p_serious: serious,
    p_ingredient: pick.product ? null : pick.ingredient,
    p_comment: orNull(comment),
    p_product: pick.product,
    p_strength: pick.product ? pick.strength : null,
  };

  return (
    <div className="page case-view">
      <PageHead
        eyebrow={
          <>
            <Link to="/cases">Cases</Link> · {ORIGIN_LABEL[record.origin]}
          </>
        }
        title={record.ref}
        lede={record.file_name ?? undefined}
        actions={
          <>
            {record.r2_key ? (
              <Button onClick={() => openArchived(record.r2_key!).catch((e) => setMessage({ tone: 'error', text: errorMessage(e) }))}>
                Open the document
              </Button>
            ) : null}
            {record.document?.url && safeHref(record.document.url) ? (
              <a className="btn btn-secondary" href={safeHref(record.document.url)!} target="_blank" rel="noopener noreferrer">
                The paper
              </a>
            ) : null}
          </>
        }
      />

      <section className="panel case-state">
        <div className="case-state-row">
          <Tag tone={status === 'failed' ? 'danger' : status === 'to_confirm' ? 'warning' : status === 'sent' ? 'success' : 'neutral'}>
            {STATUS_LABEL[status]}
          </Tag>
          <span className="case-clock">{clockLine(due, today, isOpen(status))}</span>
          <span className="case-sub">
            Day zero {formatDate(record.day_zero)} · {serious === false ? '90 days: not serious' : '15 days: serious or not yet decided'}
          </span>
        </div>
        {status === 'queued' || status === 'reading' ? (
          <Notice>PHAROS is reading the document. The form appears here in a few minutes.</Notice>
        ) : null}
        {record.read_error ? <Notice tone="error">{record.read_error}</Notice> : null}
        {record.extracted?.is_case === false ? (
          <Notice tone="error">PHAROS found no individual patient with an adverse event in this document. Check it before you go on.</Notice>
        ) : null}
        {record.extracted?.notes ? <Notice>{record.extracted.notes}</Notice> : null}
        {status === 'sent' ? (
          <p className="case-sub">
            Sent {formatDate(record.sent_on)} · reference {record.authority_ref}
          </p>
        ) : null}
        {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      </section>

      <section className="panel">
        <SectionHead index="01" title="A valid case" aside={record.read_at ? `Read ${formatDateTime(record.read_at)}` : undefined} />
        <ul className="case-criteria">
          {['patient', 'reporter', 'product', 'reaction'].map((k) => (
            <li key={k} className={missing.includes(k) ? 'is-missing' : 'is-present'}>
              <span>{MISSING_LABEL[k]}</span>
              <Tag tone={missing.includes(k) ? 'danger' : 'success'}>{missing.includes(k) ? 'Missing' : 'Present'}</Tag>
            </li>
          ))}
        </ul>
        <div className="form-grid">
          <Field
            label="Seriousness"
            hint={record.extracted?.serious ? `PHAROS read it as ${record.extracted.serious === 'yes' ? 'serious' : 'not serious'}` : undefined}
          >
            <Select
              value={serious === null ? '' : serious ? 'yes' : 'no'}
              onChange={(e) => {
                setSerious(e.target.value === '' ? null : e.target.value === 'yes');
                setDirty(true);
              }}
              disabled={!editable}
              options={[
                { value: '', label: 'Not decided (15 days)' },
                { value: 'yes', label: 'Serious (15 days)' },
                { value: 'no', label: 'Not serious (90 days)' },
              ]}
            />
          </Field>
          <ProductPick
            value={pick}
            ingredients={ingredients.data ?? []}
            current={record.product_id}
            placeholder="Choose the product or the ingredient"
            disabled={!editable}
            onChange={(next, product, strength) => {
              setPick(next);
              setDirty(true);
              // A product fills the suspect drug line: its name and strength, each ingredient with its amount.
              if (product) edit(withSuspect(draft, suspectLine(product, strength)));
            }}
          />
          <Choice label="Type of report" value={draft.report_type} options={REPORT_TYPE} onChange={(v) => edit({ ...draft, report_type: v })} disabled={!editable} />
          <TextField label="Country (two letters)" value={draft.country} onChange={(v) => edit({ ...draft, country: orNull(v)?.toUpperCase().slice(0, 2) ?? null })} disabled={!editable} />
        </div>
      </section>

      <section className="panel">
        <SectionHead index="02" title="The case form" aside={dirty ? 'Not saved' : undefined} />
        <Group title="Patient">
          <div className="form-grid">
            <TextField label="Initials" value={patient.initials} onChange={(v) => setPatient('initials', orNull(v))} disabled={!editable} />
            <Choice label="Sex" value={patient.sex} options={SEX} onChange={(v) => setPatient('sex', v)} disabled={!editable} />
            <TextField label="Age" value={patient.age_value} onChange={(v) => setPatient('age_value', numberOrNull(v))} disabled={!editable} />
            <Choice label="Age in" value={patient.age_unit} options={AGE_UNIT} onChange={(v) => setPatient('age_unit', v)} disabled={!editable} />
            <Choice label="Age group" value={patient.age_group} options={AGE_GROUP} onChange={(v) => setPatient('age_group', v)} disabled={!editable} />
            <TextField label="Birth date" value={patient.birth_date} onChange={(v) => setPatient('birth_date', orNull(v))} disabled={!editable} hint="YYYY-MM-DD, YYYY-MM or YYYY" />
            <TextField label="Weight (kg)" value={patient.weight_kg} onChange={(v) => setPatient('weight_kg', numberOrNull(v))} disabled={!editable} />
          </div>
          <Toggle label="Pregnant" checked={patient.pregnant === true} onChange={(b) => setPatient('pregnant', b ? true : null)} disabled={!editable} />
          <Field label="Medical history">
            <Textarea value={patient.medical_history ?? ''} onChange={(e) => setPatient('medical_history', orNull(e.target.value))} disabled={!editable} rows={2} />
          </Field>
          {historyCodes.map((h, k) => (
            <MeshCoding
              key={`${h.mesh_ui}-${k}`}
              label={h.text ? `History: ${h.text}` : 'History'}
              ui={h.mesh_ui}
              term={h.mesh_term}
              suggestions={[]}
              editable={editable}
              onChoose={(ui, name) =>
                setPatient(
                  'history_codes',
                  ui
                    ? historyCodes.map((x, j) => (j === k ? { ...x, mesh_ui: ui, mesh_term: name ?? '' } : x))
                    : historyCodes.filter((_, j) => j !== k),
                )
              }
            />
          ))}
          {(coding?.history ?? [])
            .filter((w) => !historyCodes.some((h) => (h.text ?? '') === w.text))
            .map((w) => (
              <MeshCoding
                key={w.norm}
                label={`History: ${w.text}`}
                ui={null}
                term={null}
                suggestions={w.suggestions}
                editable={editable}
                onChoose={(ui, name) =>
                  ui ? setPatient('history_codes', [...historyCodes, { text: w.text, mesh_ui: ui, mesh_term: name ?? '' }]) : undefined
                }
              />
            ))}
          <Quotes evidence={evidence} prefix="patient" />
        </Group>

        <Group title="Reporter">
          <div className="form-grid">
            <TextField label="Name" value={reporter.name} onChange={(v) => setReporter('name', orNull(v))} disabled={!editable} />
            <Choice label="Qualification" value={reporter.qualification} options={QUALIFICATION} onChange={(v) => setReporter('qualification', v)} disabled={!editable} />
            <TextField label="Organisation" value={reporter.organisation} onChange={(v) => setReporter('organisation', orNull(v))} disabled={!editable} />
            <TextField label="Country (two letters)" value={reporter.country} onChange={(v) => setReporter('country', orNull(v)?.toUpperCase().slice(0, 2) ?? null)} disabled={!editable} />
            <TextField label="Email" value={reporter.email} onChange={(v) => setReporter('email', orNull(v))} disabled={!editable} />
            <TextField label="Phone" value={reporter.phone} onChange={(v) => setReporter('phone', orNull(v))} disabled={!editable} />
          </div>
          <Field label="Literature reference" hint="For a published article: authors, title, journal, year">
            <Textarea value={draft.literature_reference ?? ''} onChange={(e) => edit({ ...draft, literature_reference: orNull(e.target.value) })} disabled={!editable} rows={2} />
          </Field>
          <Quotes evidence={evidence} prefix="reporter" />
        </Group>

        <Group
          title="Products"
          aside={editable ? <Button size="sm" onClick={() => edit({ ...draft, products: [...products, { role: 'suspect' }] })}>Add a product</Button> : null}
        >
          {products.map((p, i) => (
            <div key={i} className="case-item">
              <div className="form-grid">
                <TextField label="Product" value={p.name} onChange={(v) => setProduct(i, 'name', orNull(v))} disabled={!editable} />
                <TextField label="Active ingredient" value={p.active_ingredient} onChange={(v) => setProduct(i, 'active_ingredient', orNull(v))} disabled={!editable} />
                <Choice label="Role" value={p.role} options={ROLE} onChange={(v) => setProduct(i, 'role', v)} disabled={!editable} />
                <TextField label="Dose" value={p.dose} onChange={(v) => setProduct(i, 'dose', orNull(v))} disabled={!editable} />
                <TextField label="Route" value={p.route} onChange={(v) => setProduct(i, 'route', orNull(v))} disabled={!editable} />
                <TextField label="Indication" value={p.indication} onChange={(v) => setProduct(i, 'indication', orNull(v))} disabled={!editable} />
                <TextField label="Started" value={p.start_date} onChange={(v) => setProduct(i, 'start_date', orNull(v))} disabled={!editable} />
                <TextField label="Stopped" value={p.stop_date} onChange={(v) => setProduct(i, 'stop_date', orNull(v))} disabled={!editable} />
                <Choice label="Action taken" value={p.action_taken} options={ACTION} onChange={(v) => setProduct(i, 'action_taken', v)} disabled={!editable} />
                <TextField label="Batch" value={p.batch} onChange={(v) => setProduct(i, 'batch', orNull(v))} disabled={!editable} />
              </div>
              <div className="case-ingredients">
                {(p.ingredients ?? []).map((x, k) => (
                  <div key={k} className="form-grid case-ingredient">
                    <TextField label={`Ingredient ${k + 1}`} value={x.name} onChange={(v) => setIngredientLine(i, k, 'name', orNull(v))} disabled={!editable} />
                    <AmountField label="Amount" value={x.amount} onChange={(v) => setIngredientLine(i, k, 'amount', v)} disabled={!editable} />
                    <Choice
                      label="Unit"
                      value={x.unit}
                      options={UNITS.map((u) => ({ value: u, label: u }))}
                      onChange={(v) => setIngredientLine(i, k, 'unit', v)}
                      disabled={!editable}
                    />
                    {editable ? (
                      <Button
                        size="sm"
                        variant="quiet"
                        onClick={() => setProduct(i, 'ingredients', (p.ingredients ?? []).filter((_, j) => j !== k))}
                      >
                        Remove this ingredient
                      </Button>
                    ) : null}
                  </div>
                ))}
                {editable ? (
                  <Button
                    size="sm"
                    variant="quiet"
                    onClick={() => setProduct(i, 'ingredients', [...(p.ingredients ?? []), { name: null, amount: null, unit: 'mg' }])}
                  >
                    Add an ingredient with its amount
                  </Button>
                ) : null}
              </div>
              <DrugCoding
                rxcui={p.rxcui}
                name={p.rxnorm_name}
                unii={p.unii}
                suggestions={suggestionsFor(coding?.products, `${p.name ?? ''} ${p.active_ingredient ?? ''}`)}
                editable={editable}
                onChoose={(d) => chooseDrug(i, d)}
              />
              {p.indication ? (
                <MeshCoding
                  label="Indication code"
                  ui={p.indication_mesh_ui}
                  term={p.indication_mesh_term}
                  suggestions={suggestionsFor(coding?.items, p.indication)}
                  editable={editable}
                  onChoose={(ui, name) =>
                    edit({
                      ...draft,
                      products: products.map((x, j) => (j === i ? { ...x, indication_mesh_ui: ui, indication_mesh_term: name } : x)),
                    })
                  }
                />
              ) : null}
              {editable ? (
                <Button size="sm" variant="quiet" onClick={() => edit({ ...draft, products: products.filter((_, j) => j !== i) })}>
                  Remove this product
                </Button>
              ) : null}
            </div>
          ))}
          <Quotes evidence={evidence} prefix="products" />
        </Group>

        <Group
          title="Reactions"
          aside={editable ? <Button size="sm" onClick={() => edit({ ...draft, reactions: [...reactions, { criteria: [] }] })}>Add a reaction</Button> : null}
        >
          {reactions.map((r, i) => (
            <div key={i} className="case-item">
              <div className="form-grid">
                <TextField label="As the reporter wrote it" value={r.verbatim} onChange={(v) => setReaction(i, 'verbatim', orNull(v))} disabled={!editable} />
                <TextField label="In English" value={r.english} onChange={(v) => setReaction(i, 'english', orNull(v))} disabled={!editable} />
                <TextField label="MedDRA LLT code" value={r.meddra_llt_code} onChange={(v) => setReaction(i, 'meddra_llt_code', orNull(v))} disabled={!editable} hint="8 digits, from the MedDRA browser" />
                <TextField label="MedDRA version" value={r.meddra_version} onChange={(v) => setReaction(i, 'meddra_version', orNull(v))} disabled={!editable} hint="e.g. 28.1" />
                <TextField label="Started" value={r.onset_date} onChange={(v) => setReaction(i, 'onset_date', orNull(v))} disabled={!editable} />
                <TextField label="Ended" value={r.end_date} onChange={(v) => setReaction(i, 'end_date', orNull(v))} disabled={!editable} />
                <Choice label="Outcome" value={r.outcome} options={OUTCOME} onChange={(v) => setReaction(i, 'outcome', v)} disabled={!editable} />
              </div>
              <MeshCoding
                label="Reaction code"
                ui={r.mesh_ui}
                term={r.mesh_term}
                suggestions={suggestionsFor(coding?.items, r.english || r.verbatim, r.verbatim)}
                editable={editable}
                onChoose={(ui, name) =>
                  edit({ ...draft, reactions: reactions.map((x, j) => (j === i ? { ...x, mesh_ui: ui, mesh_term: name } : x)) })
                }
              />
              {listedFor.map((x) => (
                <Listed key={x.id} ingredientId={x.id} ui={r.mesh_ui} who={x.who} />
              ))}
              <div className="case-criteria-pick">
                {CRITERIA.map((k) => (
                  <Toggle
                    key={k.value}
                    label={k.label}
                    checked={(r.criteria ?? []).includes(k.value)}
                    disabled={!editable}
                    onChange={(b) =>
                      setReaction(i, 'criteria', b ? [...(r.criteria ?? []), k.value] : (r.criteria ?? []).filter((x) => x !== k.value))
                    }
                  />
                ))}
              </div>
              {editable ? (
                <Button size="sm" variant="quiet" onClick={() => edit({ ...draft, reactions: reactions.filter((_, j) => j !== i) })}>
                  Remove this reaction
                </Button>
              ) : null}
            </div>
          ))}
          <Quotes evidence={evidence} prefix="reactions" />
          <div className="code-status">
            <span className="code-sub">
              {record.coding_status === 'queued'
                ? 'PHAROS is suggesting the codes…'
                : record.coding_status === 'failed'
                  ? record.coding_error ?? 'The codes could not be suggested.'
                  : coding
                    ? `Codes suggested ${formatDateTime(coding.at)}${coding.reader ? '' : ' from MeSH’s closest names'}.`
                    : 'The codes are suggested once the case is read.'}
              {coding?.note ? ` ${coding.note}` : ''}
            </span>
            {editable && record.coding_status !== 'queued' ? (
              <Button
                size="sm"
                busy={busy}
                disabled={dirty}
                title={dirty ? 'Save first: the codes are suggested from the saved form' : undefined}
                onClick={() => ask('code', 'PHAROS is suggesting the codes again.')}
              >
                Suggest the codes again
              </Button>
            ) : null}
          </div>
          <CodingSource mesh={coding?.mesh} />
        </Group>

        <Group title="Narrative and assessment">
          <Field label="Narrative">
            <Textarea value={draft.narrative ?? ''} onChange={(e) => edit({ ...draft, narrative: orNull(e.target.value) })} disabled={!editable} rows={8} />
          </Field>
          <Field label="The reporter's assessment">
            <Textarea value={draft.causality ?? ''} onChange={(e) => edit({ ...draft, causality: orNull(e.target.value) })} disabled={!editable} rows={2} />
          </Field>
        </Group>
      </section>

      {canReview ? (
        <section className="panel">
          <SectionHead index="03" title="Decide" />
          <Field label="Comment" hint="Kept in the history with the step">
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} />
          </Field>
          {editable ? (
            <div className="case-actions">
              <Button busy={busy} disabled={!dirty} onClick={() => rpc('save_case', formArgs, 'Saved.')}>
                Save
              </Button>
              <Button
                variant="primary"
                busy={busy}
                disabled={missing.length > 0 || serious === null || !(pick.ingredient || pick.product)}
                title={missing.length > 0 ? `Missing ${missing.map((m) => MISSING_LABEL[m]).join(', ')}` : undefined}
                onClick={() => rpc('confirm_case', formArgs, 'Confirmed. The case is ready for the authority.')}
              >
                Confirm the case
              </Button>
              <Button
                variant="danger"
                busy={busy}
                disabled={!comment.trim()}
                title="Write why in the comment first"
                onClick={() => rpc('case_not_valid', { p_case: record.id, p_seen: seen, p_comment: comment }, 'Marked not valid.')}
              >
                Not a valid case
              </Button>
              {status === 'to_confirm' || status === 'failed' ? (
                <Button busy={busy} onClick={() => ask('read', 'PHAROS will read the document again.')}>
                  Read again
                </Button>
              ) : null}
            </div>
          ) : null}

          {status === 'confirmed' ? (
            <div className="form-grid case-sent">
              <TextField label="Sent on" type="date" value={sentOn} onChange={setSentOn} disabled={busy} />
              <TextField label="The authority's reference" value={authorityRef} onChange={setAuthorityRef} disabled={busy} />
              <div className="case-actions">
                <Button
                  variant="primary"
                  busy={busy}
                  disabled={!authorityRef.trim() || dirty}
                  onClick={() =>
                    rpc(
                      'case_sent',
                      { p_case: record.id, p_seen: seen, p_sent_on: sentOn, p_ref: authorityRef.trim(), p_comment: orNull(comment) },
                      'Recorded as sent.',
                    )
                  }
                >
                  Record as sent
                </Button>
              </div>
            </div>
          ) : null}

          {status === 'sent' || status === 'not_valid' || status === 'confirmed' ? (
            <div className="form-grid case-reopen">
              <TextField label="New day zero (a follow-up)" type="date" value={newDayZero} onChange={setNewDayZero} disabled={busy} />
              <div className="case-actions">
                <Button
                  busy={busy}
                  disabled={!comment.trim()}
                  title="Write why in the comment first"
                  onClick={() =>
                    rpc(
                      'reopen_case',
                      { p_case: record.id, p_seen: seen, p_comment: comment, p_day_zero: newDayZero || null },
                      'Reopened.',
                    )
                  }
                >
                  Reopen
                </Button>
              </div>
            </div>
          ) : null}

          <div className="case-actions">
            <Button busy={busy} disabled={!comment.trim()} onClick={() => rpc('case_note', { p_case: record.id, p_comment: comment }, 'Note added.')}>
              Add the comment as a note
            </Button>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <SectionHead index={canReview ? '04' : '03'} title="E2B(R3) file" />
        <p className="case-hint">
          The file the authority's gateway takes, made from the confirmed form. MedDRA codes are typed by you from the
          MedDRA browser; PHAROS never invents one. Until the first file has passed the authority's gateway test, treat it
          as a prepared draft and check it before sending. Without MedDRA codes, send the CIOMS I form below instead.
        </p>
        {record.e2b_status === 'queued' ? <Notice>The file is being made.</Notice> : null}
        {record.e2b_status === 'failed' && record.e2b_error ? <Notice tone="error">{record.e2b_error}</Notice> : null}
        {record.e2b_r2_key ? (
          <p className="case-file">
            <Button onClick={() => openArchived(record.e2b_r2_key!).catch((e) => setMessage({ tone: 'error', text: errorMessage(e) }))}>
              Open the E2B file
            </Button>
            <span className="case-sub">
              Made {formatDateTime(record.e2b_at)} · SHA-256 <span className="mono">{record.e2b_sha256}</span>
            </span>
          </p>
        ) : null}
        {canReview && (status === 'confirmed' || status === 'sent') ? (
          <>
            {e2bIssues.length > 0 ? <Notice tone="error">The file needs: {e2bIssues.join('; ')}.</Notice> : null}
            <div className="case-actions">
              <Button
                busy={busy || record.e2b_status === 'queued'}
                disabled={e2bIssues.length > 0 || dirty}
                onClick={() => ask('e2b', 'PHAROS is making the E2B file.')}
              >
                {record.e2b_r2_key ? 'Make the file again' : 'Make the E2B file'}
              </Button>
            </div>
          </>
        ) : null}
      </section>

      <section className="panel">
        <SectionHead index={canReview ? '05' : '04'} title="CIOMS I form" />
        <p className="case-hint">
          The one-page report authorities take by e-mail, made from the confirmed form. The reactions go in the
          reporter's words, so it needs no MedDRA code. It opens in a new tab: save it as PDF from there and attach it.
        </p>
        {canReview && (status === 'confirmed' || status === 'sent') ? (
          <>
            {ciomsIssues.length > 0 ? <Notice tone="error">The form needs: {ciomsIssues.join('; ')}.</Notice> : null}
            <div className="case-actions">
              <Button
                disabled={ciomsIssues.length > 0 || dirty}
                title={dirty ? 'Save the case first' : undefined}
                onClick={() =>
                  openPage(
                    ciomsHtml({
                      form: draft,
                      ref: record.ref,
                      dayZero: record.day_zero,
                      serious,
                      followUp: (events.data ?? []).some((e) => e.step === 'reopened'),
                      today,
                    }),
                  )
                }
              >
                Open the CIOMS I form
              </Button>
            </div>
          </>
        ) : canReview ? (
          <p className="case-sub">Confirm the case first: the form is made from the confirmed form.</p>
        ) : null}
      </section>

      <section className="panel">
        <SectionHead index={canReview ? '06' : '05'} title="History" />
        {events.isPending ? (
          <Loading />
        ) : events.isError ? (
          <ErrorNote error={events.error} onRetry={() => events.refetch()} />
        ) : (
          <ol className="case-history">
            {(events.data ?? []).map((e) => (
              <li key={e.id}>
                <span className="case-history-step">{STEP_LABEL[e.step]}</span>
                <span className="case-sub">
                  {formatDateTime(e.created_at)} · {e.person?.full_name ?? 'PHAROS'}
                </span>
                {e.comment ? <span className="case-history-comment">{e.comment}</span> : null}
              </li>
            ))}
          </ol>
        )}
        <p className="case-sub">
          Original SHA-256 <span className="mono">{record.sha256 ?? '—'}</span>
          {record.reader_model ? ` · read by ${record.reader_model}` : ''}
        </p>
      </section>
    </div>
  );
}
