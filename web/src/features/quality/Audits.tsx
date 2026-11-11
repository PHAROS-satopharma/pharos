import { useState } from 'react';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDateTime } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty } from '../../ui/States';
import { cx } from '../../ui/cx';
import { CapaCard, CapaForm } from './CapaPlan';
import { DraftPanel, type DraftUse } from './Drafts';
import { DAY, Fact, History, OwnerFields, StepButtons, WriteError, useWrite } from './parts';
import {
  type Audit,
  type AuditKind,
  type Capa,
  type Deadline,
  type Grade,
  AUDIT_STATUS_LABEL,
  DEADLINE,
  GRADE_LABEL,
  KIND_LABEL,
  auditSteps,
  capasOf,
  dayText,
  deadlineText,
  nextDeadline,
} from './quality';

/** Plan an audit, or record one whose report has arrived (audit_open). */
function OpenForm({ onDone }: { onDone: (id: string | null) => void }) {
  const write = useWrite<string>();
  const today = cairoToday();
  const [kind, setKind] = useState<AuditKind>('internal');
  const [title, setTitle] = useState('');
  const [auditor, setAuditor] = useState('');
  const [lead, setLead] = useState('');
  const [planned, setPlanned] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [report, setReport] = useState('');
  const problem =
    title.trim() === ''
      ? 'Give it a title.'
      : auditor.trim() === ''
        ? 'Name the auditor.'
        : from && to && to < from
          ? 'The visit ends on or after its first day.'
          : report && (!DAY.test(report) || report > today)
            ? 'The report was received today or earlier.'
            : null;
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (problem) return;
        write.mutate(
          {
            fn: 'audit_open',
            args: {
              p_kind: kind,
              p_title: title.trim(),
              p_auditor: auditor.trim(),
              p_lead_auditor: lead.trim() || null,
              p_planned_on: planned || null,
              p_visit_from: from || null,
              p_visit_to: to || null,
              p_report_received_on: report || null,
            },
          },
          { onSuccess: (id) => onDone(id) },
        );
      }}
    >
      <p className="q-form-what">Plan or record an audit</p>
      <p className="small muted q-wide">
        {kind === 'internal'
          ? 'An internal audit of the PV department, in the last quarter of every year. QA sends the audit plan (PV-FM-011) to the QPPV two weeks before.'
          : 'An external audit by another marketing authorisation holder under the safety data exchange agreement. The QPPV notifies the CEO, QA and the departments.'}
      </p>
      <Field label="Audit">
        <Select
          value={kind}
          options={[
            { value: 'internal', label: KIND_LABEL.internal },
            { value: 'external', label: KIND_LABEL.external },
          ]}
          onChange={(e) => setKind(e.target.value as AuditKind)}
        />
      </Field>
      <Field label="Title">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
      </Field>
      <Field label={kind === 'external' ? 'Auditor (the marketing authorisation holder)' : 'Auditor (the organisation)'}>
        <Input value={auditor} onChange={(e) => setAuditor(e.target.value)} />
      </Field>
      <Field label="Lead auditor">
        <Input value={lead} onChange={(e) => setLead(e.target.value)} />
      </Field>
      <Field label="Planned for">
        <Input type="date" value={planned} onChange={(e) => setPlanned(e.target.value)} />
      </Field>
      <Field label="Visit from">
        <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
      </Field>
      <Field label="Visit to">
        <Input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
      </Field>
      <Field label="Audit report received on" hint="Day zero: the deadlines count from it. Leave empty if not yet.">
        <Input type="date" value={report} max={today} onChange={(e) => setReport(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={Boolean(problem)}>
          Save the audit
        </Button>
        <Button variant="quiet" onClick={() => onDone(null)}>
          Cancel
        </Button>
        {problem && (title || auditor) ? <span className="q-blocked">{problem}</span> : null}
      </div>
    </form>
  );
}

/** One deadline: its words, and for a writer the day it was done. */
function DeadlineRow({ a, d, editable }: { a: Audit; d: Deadline; editable: boolean }) {
  const { canReview } = useAuth();
  const write = useWrite<string>();
  const today = cairoToday();
  const [day, setDay] = useState('');
  const [open, setOpen] = useState(false);
  const field = DEADLINE[d.key].field;
  return (
    <li className={cx('q-deadline', `is-${d.state}`)}>
      <span className="q-deadline-text">{deadlineText(d)}</span>
      {editable && canReview && a.status !== 'closed' && d.state !== 'done' ? (
        open ? (
          <form
            className="q-inline"
            onSubmit={(e) => {
              e.preventDefault();
              if (!DAY.test(day) || day > today) return;
              write.mutate(
                { fn: 'audit_update', args: { p_id: a.id, p_expected: a.status, p: { [field]: day }, p_comment: null } },
                { onSuccess: () => setOpen(false) },
              );
            }}
          >
            <Input
              type="date"
              value={day}
              max={today}
              onChange={(e) => setDay(e.target.value)}
              aria-label={`The day: ${DEADLINE[d.key].label}`}
            />
            <Button type="submit" variant="primary" busy={write.isPending} disabled={!DAY.test(day) || day > today}>
              Save
            </Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </form>
        ) : (
          <Button
            variant="quiet"
            onClick={() => {
              setDay(today);
              setOpen(true);
            }}
          >
            Done on…
          </Button>
        )
      ) : null}
      <WriteError error={write.error} />
    </li>
  );
}

/** The days of an audit that are not deadlines: the final report, the closure, a request for information. */
function DaysForm({ a, onDone }: { a: Audit; onDone: () => void }) {
  const write = useWrite<string>();
  const today = cairoToday();
  const fields = [
    ['planned_on', 'Planned for'],
    ['plan_sent_on', 'Audit plan sent to the QPPV'],
    ['visit_from', 'Visit from'],
    ['visit_to', 'Visit to'],
    ['rfi_received_on', 'Request for information received'],
    ['rfi_answered_on', 'Request for information answered'],
    ['report_received_on', 'Audit report received (day zero)'],
    ['final_report_on', 'Final report received'],
    ['closure_confirmed_on', 'Closure confirmed by the lead auditor'],
  ] as const;
  const [v, setV] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(([f]) => [f, (a[f] as string | null) ?? ''])),
  );
  const [lead, setLead] = useState(a.lead_auditor ?? '');
  const [comment, setComment] = useState('');
  const changed = fields.filter(([f]) => v[f] !== ((a[f] as string | null) ?? '')).map(([f]) => f);
  const leadChanged = lead.trim() !== (a.lead_auditor ?? '');
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        const p: Record<string, unknown> = Object.fromEntries(changed.map((f) => [f, v[f] || null]));
        if (leadChanged) p.lead_auditor = lead;
        write.mutate(
          { fn: 'audit_update', args: { p_id: a.id, p_expected: a.status, p, p_comment: comment.trim() || null } },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="q-form-what">The days of this audit</p>
      <Field label="Lead auditor">
        <Input value={lead} onChange={(e) => setLead(e.target.value)} />
      </Field>
      {fields.map(([f, label]) => (
        <Field key={f} label={label}>
          <Input
            type="date"
            value={v[f]}
            max={f === 'planned_on' || f === 'visit_from' || f === 'visit_to' ? undefined : today}
            onChange={(e) => setV((x) => ({ ...x, [f]: e.target.value }))}
          />
        </Field>
      ))}
      <Field label="Comment (optional)" hint="Kept in the history with what changed." className="q-wide">
        <Input value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={changed.length === 0 && !leadChanged}>
          Save the days
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Add an observation of the audit report, graded and assigned to a stakeholder. */
function ObservationForm({ auditId, onDone }: { auditId: string; onDone: () => void }) {
  const write = useWrite<string>();
  const [text, setText] = useState('');
  const [grade, setGrade] = useState<Grade | ''>('');
  const [person, setPerson] = useState('');
  const [other, setOther] = useState('');
  const [root, setRoot] = useState('');
  const blocked = text.trim() === '' || grade === '';
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        write.mutate(
          {
            fn: 'audit_add_observation',
            args: {
              p_audit: auditId,
              p_text: text.trim(),
              p_grade: grade,
              p_assigned_to: person || null,
              p_assigned_other: person ? null : other.trim() || null,
              p_root_cause: root.trim() || null,
            },
          },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="q-form-what">New observation</p>
      <Field label="Observation" className="q-wide">
        <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <Field label="Grade">
        <Select
          value={grade}
          placeholder="Choose the grade"
          options={(['critical', 'major', 'minor'] as const).map((g) => ({ value: g, label: GRADE_LABEL[g] }))}
          onChange={(e) => setGrade(e.target.value as Grade | '')}
        />
      </Field>
      <OwnerFields label="Assigned to" personId={person} other={other} setPersonId={setPerson} setOther={setOther} />
      <Field label="Root cause" hint="If already known." className="q-wide">
        <Textarea rows={2} value={root} onChange={(e) => setRoot(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={blocked}>
          Add the observation
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** The root cause and the stakeholder of an observation, written after the meeting. */
function ObservationEdit({
  o,
  onDone,
  seedRootCause,
}: {
  o: Audit['observations'][number];
  onDone: () => void;
  seedRootCause?: string;
}) {
  const write = useWrite<null>();
  const [root, setRoot] = useState(seedRootCause || (o.root_cause ?? ''));
  const [person, setPerson] = useState(o.assigned_to ?? '');
  const [other, setOther] = useState(o.assigned_other ?? '');
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        const p: Record<string, unknown> = {};
        if (root.trim() !== (o.root_cause ?? '')) p.root_cause = root;
        if ((person || null) !== o.assigned_to) p.assigned_to = person || null;
        const otherNow = person ? null : other.trim() || null;
        if (otherNow !== o.assigned_other) p.assigned_other = otherNow;
        write.mutate({ fn: 'audit_observation_update', args: { p_id: o.id, p, p_comment: null } }, { onSuccess: onDone });
      }}
    >
      <OwnerFields label="Assigned to" personId={person} other={other} setPersonId={setPerson} setOther={setOther} />
      <Field label="Root cause" className="q-wide">
        <Textarea rows={2} value={root} onChange={(e) => setRoot(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending}>
          Save
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ObservationCard({ a, o, capas }: { a: Audit; o: Audit['observations'][number]; capas: Capa[] }) {
  const { canReview } = useAuth();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  // A draft (0109) opens the usual forms filled in; the key starts a form again with each use.
  const [seedRoot, setSeedRoot] = useState<{ text: string; n: number } | null>(null);
  const [seedCapa, setSeedCapa] = useState<{ use: DraftUse; n: number } | null>(null);
  const open = a.status !== 'closed';
  return (
    <li className="q-obs">
      <div className="q-card-head">
        <span className="q-ref">Observation {o.number}</span>
        <span className={cx('q-grade', `q-grade-${o.grade}`)}>{GRADE_LABEL[o.grade]}</span>
        <span className="q-source">Assigned to {o.assigned_name ?? 'nobody yet'}</span>
      </div>
      <p className="q-pre">{o.text}</p>
      <dl className="q-facts">
        <Fact label="Root cause" wide>
          {o.root_cause ?? <span className="soft">Not found yet</span>}
        </Fact>
      </dl>
      {canReview && open ? (
        editing ? (
          <ObservationEdit
            key={seedRoot?.n ?? 0}
            o={o}
            seedRootCause={seedRoot?.text}
            onDone={() => {
              setEditing(false);
              setSeedRoot(null);
            }}
          />
        ) : (
          <div className="button-row">
            <Button variant="quiet" onClick={() => setEditing(true)}>
              Root cause and stakeholder
            </Button>
            {!adding ? <Button onClick={() => setAdding(true)}>Add a CAPA</Button> : null}
          </div>
        )
      ) : null}
      <DraftPanel
        kind="observation"
        recordId={o.id}
        canAsk={canReview && open}
        onUseRootCause={(text) => {
          setSeedRoot((s) => ({ text, n: (s?.n ?? 0) + 1 }));
          setEditing(true);
        }}
        onUseCapa={(use) => {
          setSeedCapa((s) => ({ use, n: (s?.n ?? 0) + 1 }));
          setAdding(true);
        }}
      />
      {adding ? (
        <CapaForm
          key={seedCapa?.n ?? 0}
          observationId={o.id}
          initial={seedCapa ? { corrective: seedCapa.use.corrective, preventive: seedCapa.use.preventive } : undefined}
          onDone={() => {
            setAdding(false);
            setSeedCapa(null);
          }}
        />
      ) : null}
      {capas.length ? (
        <ul className="q-list">
          {capas.map((c) => (
            <CapaCard key={c.id} c={c} showSource={false} />
          ))}
        </ul>
      ) : (
        <p className="small muted">No CAPA yet.</p>
      )}
    </li>
  );
}

function AuditDetail({ a, capas }: { a: Audit; capas: Capa[] }) {
  const { canReview } = useAuth();
  const step = useWrite<string>();
  const [adding, setAdding] = useState(false);
  const [days, setDays] = useState(false);
  const mine = a.observations.flatMap((o) => capasOf(capas, { observation: o.id }));
  return (
    <div className="q-detail">
      <p className="small muted">Audit reports are confidential: they stay within the PV team.</p>
      <dl className="q-facts">
        <Fact label="Auditor">{a.auditor}</Fact>
        <Fact label="Lead auditor">{a.lead_auditor}</Fact>
        <Fact label="Planned for">{a.planned_on ? dayText(a.planned_on) : null}</Fact>
        <Fact label="Visit">
          {a.visit_from ? `${dayText(a.visit_from)}${a.visit_to && a.visit_to !== a.visit_from ? ` to ${dayText(a.visit_to)}` : ''}` : null}
        </Fact>
        <Fact label="Report received (day zero)">{a.report_received_on ? dayText(a.report_received_on) : 'Not yet'}</Fact>
        <Fact label="Final report">{a.final_report_on ? dayText(a.final_report_on) : 'Not yet'}</Fact>
        <Fact label="Closure confirmed">{a.closure_confirmed_on ? dayText(a.closure_confirmed_on) : 'Not yet'}</Fact>
        <Fact label="Recorded">
          {a.created_by ?? '—'}, {formatDateTime(a.created_at)}
        </Fact>
      </dl>

      {canReview && a.status !== 'closed' ? (
        days ? (
          <DaysForm a={a} onDone={() => setDays(false)} />
        ) : (
          <div className="button-row">
            <Button variant="quiet" onClick={() => setDays(true)}>
              Change the days
            </Button>
          </div>
        )
      ) : null}

      <h4 className="q-sub">Observations</h4>
      {a.observations.length ? (
        <ul className="q-list">
          {a.observations.map((o) => (
            <ObservationCard key={o.id} a={a} o={o} capas={capasOf(capas, { observation: o.id })} />
          ))}
        </ul>
      ) : (
        <p className="small muted">No observation recorded yet.</p>
      )}
      {canReview && a.status !== 'closed' ? (
        adding ? (
          <ObservationForm auditId={a.id} onDone={() => setAdding(false)} />
        ) : (
          <div className="button-row">
            <Button onClick={() => setAdding(true)}>Add an observation</Button>
          </div>
        )
      ) : null}

      {canReview ? (
        <>
          <h4 className="q-sub">Next step</h4>
          <StepButtons
            steps={auditSteps(a, mine)}
            busy={step.isPending}
            error={step.error}
            dayLabel="On"
            take={(s, v) =>
              step.mutate({
                fn: 'audit_step',
                args: { p_id: a.id, p_to: s.to, p_expected: a.status, p_comment: v.comment || null, p_on: v.day || null },
              })
            }
          />
        </>
      ) : null}
      <History rows={a.history} />
    </div>
  );
}

/** 02 — every audit, newest first, with its deadlines from the report day; open one for its observations. */
export function Audits({ audits, capas }: { audits: Audit[]; capas: Capa[] }) {
  const { canReview } = useAuth();
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <>
      {canReview ? (
        adding ? (
          <OpenForm
            onDone={(id) => {
              setAdding(false);
              if (id) setOpenId(id);
            }}
          />
        ) : (
          <div className="button-row q-add">
            <Button variant="primary" onClick={() => setAdding(true)}>
              Plan or record an audit
            </Button>
          </div>
        )
      ) : null}
      {audits.length === 0 ? (
        <Empty title="No audit recorded.">
          <p>
            Internal audits of the PV department and external audits by a partner. Once the report is received, the
            review is due in 1 day, the meeting in 2, the draft CAPA in 10, the approval in 12 and the submission in 14.
          </p>
        </Empty>
      ) : (
        <ul className="q-list">
          {audits.map((a) => {
            const isOpen = openId === a.id;
            const next = nextDeadline(a);
            return (
              <li key={a.id} className={cx('q-card', isOpen && 'is-open', next?.state === 'late' && 'is-late')}>
                <button
                  type="button"
                  className="q-row"
                  aria-expanded={isOpen}
                  onClick={() => setOpenId(isOpen ? null : a.id)}
                >
                  <span className="q-ref">{KIND_LABEL[a.kind]}</span>
                  <span className="q-title">{a.title}</span>
                  <span className="q-row-meta">
                    <span className={cx('q-status', `q-audit-${a.status}`)}>{AUDIT_STATUS_LABEL[a.status]}</span>
                    <span>{a.auditor}</span>
                    {a.report_received_on ? <span>Report {dayText(a.report_received_on)}</span> : null}
                    <span>
                      {a.observations.length} {a.observations.length === 1 ? 'observation' : 'observations'}
                    </span>
                  </span>
                </button>
                {a.deadlines.length && a.status !== 'closed' ? (
                  <ul className="q-deadlines" aria-label={`Deadlines of ${a.title}`}>
                    {a.deadlines.map((d) => (
                      <DeadlineRow key={d.key} a={a} d={d} editable={isOpen} />
                    ))}
                  </ul>
                ) : null}
                {isOpen ? <AuditDetail a={a} capas={capas} /> : null}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
