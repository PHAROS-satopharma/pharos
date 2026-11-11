import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDateTime } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { CapaCard, CapaForm } from './CapaPlan';
import { DAY, Fact, History, StepButtons, WriteError, useWrite } from './parts';
import {
  type Capa,
  type Deviation,
  type DeviationProposal,
  CAPA_STATUS_LABEL,
  PROPOSAL_SOURCE_LABEL,
  DEVIATION_STATUS_LABEL,
  INVESTIGATION,
  LEVEL_LABEL,
  capasOf,
  dayText,
  deviationSteps,
  proposalDueText,
  waitingProposals,
} from './quality';

/**
 * Record a deviation in full (form PV-FM-009). From a proposal (0108) the form starts with what PHAROS found;
 * she changes what she wants, and saving records the deviation and links the proposal to it.
 */
function RecordForm({ onDone, from }: { onDone: (id: string | null) => void; from?: DeviationProposal }) {
  const write = useWrite<string>();
  const today = cairoToday();
  const [title, setTitle] = useState(from?.title ?? '');
  const [description, setDescription] = useState(from?.description ?? '');
  const [occurred, setOccurred] = useState(from?.occurred_on ?? '');
  const [detected, setDetected] = useState(from?.detected_on ?? today);
  const [safety, setSafety] = useState(from?.patient_safety ?? false);
  const [compliance, setCompliance] = useState(from?.regulatory_compliance ?? false);
  const [documents, setDocuments] = useState(from?.document_quality ?? false);
  const problem =
    title.trim() === ''
      ? 'Give it a title.'
      : description.trim() === ''
        ? 'Describe it in full.'
        : !DAY.test(detected) || detected > today
          ? 'Give the day it was detected (today or earlier).'
          : occurred && occurred > detected
            ? 'It happened on or before the day it was detected.'
            : null;
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (problem) return;
        write.mutate(
          {
            fn: from ? 'deviation_proposal_confirm' : 'deviation_open',
            args: {
              ...(from ? { p_id: from.id } : {}),
              p_title: title.trim(),
              p_description: description.trim(),
              p_occurred_on: occurred || null,
              p_detected_on: detected,
              p_patient_safety: safety,
              p_regulatory_compliance: compliance,
              p_document_quality: documents,
            },
          },
          { onSuccess: (id) => onDone(id) },
        );
      }}
    >
      <p className="q-form-what">
        {from ? 'Record this missed deadline as a deviation (form PV-FM-009)' : 'Record a deviation (form PV-FM-009)'}
      </p>
      <p className="small muted q-wide">
        An unexpected, unplanned event that results in a potential risk to patient safety or product quality, or is a
        breach of the SOPs. Record it in full and notify QA at once; QA sets its level.
      </p>
      <Field label="Title" className="q-wide">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
      </Field>
      <Field label="What happened, in full" className="q-wide">
        <Textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label="Happened on" hint="If known.">
        <Input type="date" value={occurred} max={detected || today} onChange={(e) => setOccurred(e.target.value)} />
      </Field>
      <Field label="Detected on">
        <Input type="date" value={detected} max={today} onChange={(e) => setDetected(e.target.value)} />
      </Field>
      <fieldset className="q-impact q-wide">
        <legend className="field-label">Potential impact on</legend>
        <Toggle label="Patient safety" checked={safety} onChange={setSafety} />
        <Toggle label="Regulatory compliance" checked={compliance} onChange={setCompliance} />
        <Toggle label="Document quality" checked={documents} onChange={setDocuments} />
      </fieldset>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={Boolean(problem)}>
          Record the deviation
        </Button>
        <Button variant="quiet" onClick={() => onDone(null)}>
          Cancel
        </Button>
        {problem && (title || description) ? <span className="q-blocked">{problem}</span> : null}
      </div>
    </form>
  );
}

/** QA sets the level, with the reason. */
function LevelForm({ d }: { d: Deviation }) {
  const write = useWrite<string>();
  const [level, setLevel] = useState<string>(d.level ? String(d.level) : '');
  const [comment, setComment] = useState('');
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <div className="button-row">
        <Button onClick={() => setOpen(true)}>{d.level ? 'Change the level' : 'QA: set the level'}</Button>
        <WriteError error={write.error} />
      </div>
    );
  }
  const blocked = level === '' || Number(level) === d.level || comment.trim() === '';
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        write.mutate(
          { fn: 'deviation_set_level', args: { p_id: d.id, p_expected: d.status, p_level: Number(level), p_comment: comment.trim() } },
          { onSuccess: () => setOpen(false) },
        );
      }}
    >
      <Field label="Level" hint={level ? LEVEL_LABEL[Number(level) as 1 | 2 | 3].hint : 'QA sets the criticality.'}>
        <Select
          value={level}
          placeholder="Choose the level"
          options={([1, 2, 3] as const).map((l) => ({ value: String(l), label: LEVEL_LABEL[l].label }))}
          onChange={(e) => setLevel(e.target.value)}
        />
      </Field>
      <Field label="Why (required)" hint="Kept in the history for the record." className="q-wide">
        <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={blocked}>
          Record the level
        </Button>
        <Button variant="quiet" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

const EDIT_FIELDS = ['title', 'description', ...INVESTIGATION.map((q) => q.field), 'root_cause'] as const;
type EditField = (typeof EDIT_FIELDS)[number];

/** The description, the six investigation answers and the root cause, while the deviation is not closed. */
function InvestigationForm({ d, onDone }: { d: Deviation; onDone: () => void }) {
  const write = useWrite<string>();
  const [v, setV] = useState<Record<EditField, string>>(
    () => Object.fromEntries(EDIT_FIELDS.map((f) => [f, String(d[f] ?? '')])) as Record<EditField, string>,
  );
  const [comment, setComment] = useState('');
  const changed = EDIT_FIELDS.filter((f) => v[f].trim() !== String(d[f] ?? '').trim());
  const blocked = changed.length === 0 || v.title.trim() === '' || v.description.trim() === '';
  const set = (f: EditField) => (e: { target: { value: string } }) => setV((x) => ({ ...x, [f]: e.target.value }));
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        const p = Object.fromEntries(changed.map((f) => [f, v[f]]));
        write.mutate(
          { fn: 'deviation_update', args: { p_id: d.id, p_expected: d.status, p, p_comment: comment.trim() || null } },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="q-form-what">The investigation of {d.ref}</p>
      <Field label="Title" className="q-wide">
        <Input value={v.title} onChange={set('title')} maxLength={200} />
      </Field>
      <Field label="What happened, in full" className="q-wide">
        <Textarea rows={3} value={v.description} onChange={set('description')} />
      </Field>
      {INVESTIGATION.map((q) => (
        <Field key={q.field} label={q.question} className="q-wide">
          <Textarea rows={2} value={v[q.field]} onChange={set(q.field)} />
        </Field>
      ))}
      <Field label="Root cause" className="q-wide">
        <Textarea rows={2} value={v.root_cause} onChange={set('root_cause')} />
      </Field>
      <Field label="Comment (optional)" hint="Kept in the history with what changed." className="q-wide">
        <Input value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={blocked}>
          Save the investigation
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function impactWords(d: Deviation): string {
  const w = [
    d.patient_safety ? 'patient safety' : null,
    d.regulatory_compliance ? 'regulatory compliance' : null,
    d.document_quality ? 'document quality' : null,
  ].filter(Boolean);
  return w.length ? w.join(', ') : 'none marked';
}

function DeviationDetail({ d, capas }: { d: Deviation; capas: Capa[] }) {
  const { canReview } = useAuth();
  const step = useWrite<string>();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const closed = d.status === 'closed';
  return (
    <div className="q-detail">
      <dl className="q-facts">
        <Fact label="What happened" wide>
          <span className="q-pre">{d.description}</span>
        </Fact>
        <Fact label="Happened on">{d.occurred_on ? dayText(d.occurred_on) : 'Not known'}</Fact>
        <Fact label="Detected on">{dayText(d.detected_on)}</Fact>
        <Fact label="Potential impact on">{impactWords(d)}</Fact>
        <Fact label="Level">{d.level ? `${LEVEL_LABEL[d.level].label}: ${LEVEL_LABEL[d.level].hint}` : 'Not set yet'}</Fact>
        <Fact label="Recorded">
          {d.created_by ?? '—'}, {formatDateTime(d.created_at)}
        </Fact>
        <Fact label="QA satisfactory">
          {d.qa_satisfactory === null ? 'Not decided yet' : d.qa_satisfactory ? 'Satisfactory' : 'Not satisfactory'}
          {d.approved_by ? ` · approved by ${d.approved_by}, ${formatDateTime(d.approved_at)}` : ''}
        </Fact>
        {d.closed_at ? (
          <Fact label="Closed">
            {d.closed_by ?? '—'}, {formatDateTime(d.closed_at)}
          </Fact>
        ) : null}
      </dl>

      <h4 className="q-sub">Investigation</h4>
      <dl className="q-facts q-answers">
        {INVESTIGATION.map((q) => (
          <Fact key={q.field} label={q.question} wide>
            {d[q.field] ?? <span className="soft">Not answered yet</span>}
          </Fact>
        ))}
        <Fact label="Root cause" wide>
          {d.root_cause ?? <span className="soft">Not found yet</span>}
        </Fact>
      </dl>
      {canReview && !closed ? (
        editing ? (
          <InvestigationForm d={d} onDone={() => setEditing(false)} />
        ) : (
          <div className="button-row">
            <Button onClick={() => setEditing(true)}>Write the investigation</Button>
          </div>
        )
      ) : null}
      {canReview && !closed ? <LevelForm d={d} /> : null}

      <h4 className="q-sub">CAPA</h4>
      {capas.length ? (
        <ul className="q-list">
          {capas.map((c) => (
            <CapaCard key={c.id} c={c} showSource={false} />
          ))}
        </ul>
      ) : (
        <p className="small muted">No CAPA yet.</p>
      )}
      {canReview && !closed ? (
        adding ? (
          <CapaForm deviationId={d.id} onDone={() => setAdding(false)} />
        ) : (
          <div className="button-row">
            <Button onClick={() => setAdding(true)}>Add a CAPA</Button>
          </div>
        )
      ) : null}

      {canReview ? (
        <>
          <h4 className="q-sub">Next step</h4>
          <StepButtons
            steps={deviationSteps(d, capas)}
            busy={step.isPending}
            error={step.error}
            take={(s, v) =>
              step.mutate({
                fn: 'deviation_step',
                args: {
                  p_id: d.id,
                  p_to: s.to,
                  p_expected: d.status,
                  p_comment: v.comment || null,
                  p_satisfactory: s.satisfactory ?? null,
                },
              })
            }
          />
        </>
      ) : null}
      <History rows={d.history} />
    </div>
  );
}

/** 01 — every deviation, newest first; open one to see it in full and take its next step. */
/** Dismiss a proposal: the reason is required, kept, and listed in the inspection pack. */
function DismissForm({ p, onDone }: { p: DeviationProposal; onDone: () => void }) {
  const write = useWrite<string>();
  const [reason, setReason] = useState('');
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (reason.trim() === '') return;
        write.mutate({ fn: 'deviation_proposal_dismiss', args: { p_id: p.id, p_reason: reason.trim() } }, { onSuccess: onDone });
      }}
    >
      <Field
        label="Why it is not a deviation (required)"
        hint="Kept with the proposal and listed in the inspection pack."
        className="q-wide"
      >
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={reason.trim() === ''}>
          Dismiss
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/**
 * The missed deadlines PHAROS proposed as deviations (0108): each waits for a reviewer to record it (the form
 * starts with what PHAROS found) or dismiss it with the reason. PHAROS never records one itself.
 */
export function ProposedDeviations({
  proposals,
  onRecorded,
}: {
  proposals: DeviationProposal[];
  onRecorded: (id: string) => void;
}) {
  const { canReview } = useAuth();
  const [acting, setActing] = useState<{ id: string; what: 'record' | 'dismiss' } | null>(null);
  const waiting = waitingProposals(proposals);
  const dismissed = proposals.filter((p) => p.status === 'dismissed').length;
  if (waiting.length === 0 && dismissed === 0) return null;
  return (
    <div className="q-proposals">
      <p className="q-proposals-head">
        <strong>
          {waiting.length === 0
            ? 'No missed deadline waits.'
            : `${waiting.length} missed ${waiting.length === 1 ? 'deadline' : 'deadlines'} proposed as ${waiting.length === 1 ? 'a deviation' : 'deviations'}`}
        </strong>
        <span className="small muted">
          {' '}
          PHAROS proposes each deadline it keeps that passed unmet. Record it as a deviation or dismiss it with the reason.
          {dismissed ? ` ${dismissed} dismissed so far, listed in the inspection pack.` : ''}
        </span>
      </p>
      {waiting.length ? (
        <ul className="q-list">
          {waiting.map((p) => {
            const act = acting?.id === p.id ? acting.what : null;
            return (
              <li key={p.id} className="q-card is-late q-pad">
                <div className="q-card-head">
                  <span className="q-source">{PROPOSAL_SOURCE_LABEL[p.source_kind]}</span>
                  <span className="q-title">{p.title}</span>
                </div>
                <p className="small">{p.description}</p>
                <p className="small muted">
                  {proposalDueText(p)}
                  {p.ingredient_id ? (
                    <>
                      {' · '}
                      <Link to={`/ingredients/${p.ingredient_id}`}>Open the ingredient</Link>
                    </>
                  ) : null}
                </p>
                {canReview ? (
                  act === 'record' ? (
                    <RecordForm
                      from={p}
                      onDone={(id) => {
                        setActing(null);
                        if (id) onRecorded(id);
                      }}
                    />
                  ) : act === 'dismiss' ? (
                    <DismissForm p={p} onDone={() => setActing(null)} />
                  ) : (
                    <div className="button-row">
                      <Button variant="primary" onClick={() => setActing({ id: p.id, what: 'record' })}>
                        Record as deviation
                      </Button>
                      <Button variant="quiet" onClick={() => setActing({ id: p.id, what: 'dismiss' })}>
                        Dismiss
                      </Button>
                    </div>
                  )
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function Deviations({
  deviations,
  capas,
  proposals = [],
}: {
  deviations: Deviation[];
  capas: Capa[];
  proposals?: DeviationProposal[];
}) {
  const { canReview } = useAuth();
  const [recording, setRecording] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [recorded, setRecorded] = useState(false);
  return (
    <>
      <ProposedDeviations
        proposals={proposals}
        onRecorded={(id) => {
          setOpenId(id);
          setRecorded(true);
        }}
      />
      {canReview ? (
        recording ? (
          <RecordForm
            onDone={(id) => {
              setRecording(false);
              if (id) {
                setOpenId(id);
                setRecorded(true);
              }
            }}
          />
        ) : (
          <div className="button-row q-add">
            <Button variant="primary" onClick={() => setRecording(true)}>
              Record a deviation
            </Button>
          </div>
        )
      ) : null}
      {recorded ? <Notice tone="ok">Recorded. Notify QA now; QA sets its level.</Notice> : null}
      {deviations.length === 0 ? (
        <Empty title="No deviation recorded.">
          <p>A deviation is numbered D001/2026, D002/2026 … in the order it is recorded; the numbers start again each year.</p>
        </Empty>
      ) : (
        <ul className="q-list">
          {deviations.map((d) => {
            const mine = capasOf(capas, { deviation: d.id });
            const isOpen = openId === d.id;
            return (
              <li key={d.id} className={cx('q-card', isOpen && 'is-open')}>
                <button
                  type="button"
                  className="q-row"
                  aria-expanded={isOpen}
                  onClick={() => setOpenId(isOpen ? null : d.id)}
                >
                  <span className="q-ref">{d.ref}</span>
                  <span className="q-title">{d.title}</span>
                  <span className="q-row-meta">
                    <span className={cx('q-status', `q-dev-${d.status}`)}>{DEVIATION_STATUS_LABEL[d.status]}</span>
                    <span>{d.level ? LEVEL_LABEL[d.level].label : 'Level not set'}</span>
                    <span>
                      {mine.length === 0
                        ? 'No CAPA'
                        : mine.map((c) => `${c.ref} ${CAPA_STATUS_LABEL[c.status].toLowerCase()}`).join(' · ')}
                    </span>
                  </span>
                </button>
                {isOpen ? <DeviationDetail d={d} capas={mine} /> : null}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
