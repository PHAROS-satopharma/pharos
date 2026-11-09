import { useMemo, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDateTime } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { Fact, History, OwnerFields, StepButtons, WriteError, useWrite } from './parts';
import {
  type Capa,
  type CapaSourceFilter,
  type CapaStatusFilter,
  CAPA_STATUS_LABEL,
  capaCounts,
  capaDueText,
  capaSourceText,
  capaSteps,
  filterCapas,
} from './quality';

/** Open a CAPA on one deviation or one audit observation (capa_open). */
export function CapaForm({
  deviationId,
  observationId,
  onDone,
}: {
  deviationId?: string;
  observationId?: string;
  onDone: () => void;
}) {
  const write = useWrite<string>();
  const today = cairoToday();
  const [corrective, setCorrective] = useState('');
  const [preventive, setPreventive] = useState('');
  const [owner, setOwner] = useState('');
  const [other, setOther] = useState('');
  const [due, setDue] = useState('');
  const missing = corrective.trim() === '' && preventive.trim() === '';
  const dueBad = due !== '' && due < today;
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (missing || dueBad) return;
        write.mutate(
          {
            fn: 'capa_open',
            args: {
              p_deviation: deviationId ?? null,
              p_observation: observationId ?? null,
              p_corrective: corrective.trim() || null,
              p_preventive: preventive.trim() || null,
              p_owner: owner || null,
              p_owner_other: owner ? null : other.trim() || null,
              p_due_on: due || null,
            },
          },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="q-form-what">New CAPA (form PV-FM-010)</p>
      <Field label="Corrective action" className="q-wide">
        <Textarea rows={2} value={corrective} onChange={(e) => setCorrective(e.target.value)} />
      </Field>
      <Field label="Preventive action" className="q-wide">
        <Textarea rows={2} value={preventive} onChange={(e) => setPreventive(e.target.value)} />
      </Field>
      <OwnerFields label="Owner" personId={owner} other={other} setPersonId={setOwner} setOther={setOther} />
      <Field label="Due" hint="Needed before it is approved.">
        <Input type="date" value={due} min={today} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={missing || dueBad}>
          Add the CAPA
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
        {missing ? <span className="q-blocked">Write the corrective action, the preventive action, or both.</span> : null}
      </div>
    </form>
  );
}

/** Change a CAPA's actions, owner, due day or evidence (capa_update); a due day moved after approval needs a reason. */
function CapaEdit({ c, onDone }: { c: Capa; onDone: () => void }) {
  const write = useWrite<string>();
  const today = cairoToday();
  const [corrective, setCorrective] = useState(c.corrective_action ?? '');
  const [preventive, setPreventive] = useState(c.preventive_action ?? '');
  const [owner, setOwner] = useState(c.owner_id ?? '');
  const [other, setOther] = useState(c.owner_other ?? '');
  const [due, setDue] = useState(c.due_on ?? '');
  const [evidence, setEvidence] = useState(c.evidence ?? '');
  const [comment, setComment] = useState('');
  const dueMoved = (due || null) !== c.due_on;
  const reasonNeeded = dueMoved && c.status !== 'draft';
  const blocked = (reasonNeeded && comment.trim() === '') || (dueMoved && due !== '' && due < today);
  return (
    <form
      className="q-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        const p: Record<string, unknown> = {};
        if (corrective.trim() !== (c.corrective_action ?? '')) p.corrective_action = corrective;
        if (preventive.trim() !== (c.preventive_action ?? '')) p.preventive_action = preventive;
        if ((owner || null) !== c.owner_id) p.owner_id = owner || null;
        const otherNow = owner ? null : other.trim() || null;
        if (otherNow !== c.owner_other) p.owner_other = otherNow;
        if (dueMoved) p.due_on = due || null;
        if (evidence.trim() !== (c.evidence ?? '')) p.evidence = evidence;
        write.mutate(
          { fn: 'capa_update', args: { p_id: c.id, p_expected: c.status, p, p_comment: comment.trim() || null } },
          { onSuccess: onDone },
        );
      }}
    >
      <p className="q-form-what">Change {c.ref}</p>
      <Field label="Corrective action" className="q-wide">
        <Textarea rows={2} value={corrective} onChange={(e) => setCorrective(e.target.value)} />
      </Field>
      <Field label="Preventive action" className="q-wide">
        <Textarea rows={2} value={preventive} onChange={(e) => setPreventive(e.target.value)} />
      </Field>
      <OwnerFields label="Owner" personId={owner} other={other} setPersonId={setOwner} setOther={setOther} />
      <Field label="Due">
        <Input type="date" value={due} min={today} onChange={(e) => setDue(e.target.value)} />
      </Field>
      <Field label="Evidence" hint="What was done: a document reference or a link." className="q-wide">
        <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
      </Field>
      <Field
        label={reasonNeeded ? 'Why the due day moved (required)' : 'Comment (optional)'}
        hint="Kept in the history for the record."
        className="q-wide"
      >
        <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <WriteError error={write.error} />
      <div className="button-row q-wide">
        <Button type="submit" variant="primary" busy={write.isPending} disabled={blocked}>
          Save the changes
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** One CAPA: where it comes from, the actions, owner, due, status and evidence, the next step and the history. */
export function CapaCard({ c, showSource = true }: { c: Capa; showSource?: boolean }) {
  const { canReview } = useAuth();
  const write = useWrite<string>();
  const [editing, setEditing] = useState(false);
  const late = c.status !== 'done' && c.status !== 'effective' && c.due?.state === 'late';
  const soon = c.status !== 'done' && c.status !== 'effective' && c.due?.state === 'soon';
  return (
    <li className={cx('q-card', 'q-pad', late && 'is-late')}>
      <div className="q-card-head">
        <span className="q-ref">{c.ref}</span>
        <span className={cx('q-status', `q-capa-${c.status}`)}>{CAPA_STATUS_LABEL[c.status]}</span>
        {showSource ? <span className="q-source">{capaSourceText(c)}</span> : null}
      </div>
      <dl className="q-facts">
        {c.corrective_action ? <Fact label="Corrective action" wide>{c.corrective_action}</Fact> : null}
        {c.preventive_action ? <Fact label="Preventive action" wide>{c.preventive_action}</Fact> : null}
        <Fact label="Owner">{c.owner_name}</Fact>
        <Fact label="Due">
          <span className={cx(late && 'q-late', soon && 'q-soon')}>{capaDueText(c)}</span>
        </Fact>
        {c.evidence ? <Fact label="Evidence" wide>{c.evidence}</Fact> : null}
        {c.verified_by ? (
          <Fact label="Verified effective">
            {c.verified_by}, {formatDateTime(c.verified_at)}
          </Fact>
        ) : null}
      </dl>
      {canReview ? (
        editing ? (
          <CapaEdit c={c} onDone={() => setEditing(false)} />
        ) : (
          <>
            <StepButtons
              steps={capaSteps(c)}
              busy={write.isPending}
              error={write.error}
              take={(s, v) =>
                write.mutate({
                  fn: 'capa_step',
                  args: {
                    p_id: c.id,
                    p_to: s.to,
                    p_expected: c.status,
                    p_comment: v.comment || null,
                    p_done_on: s.needsEvidence ? v.day : null,
                    p_evidence: s.needsEvidence ? v.evidence : null,
                  },
                })
              }
            />
            {c.status !== 'effective' ? (
              <div className="button-row">
                <Button variant="quiet" onClick={() => setEditing(true)}>
                  Change the CAPA
                </Button>
              </div>
            ) : null}
          </>
        )
      ) : null}
      <History rows={c.history} />
    </li>
  );
}

const STATUS_FILTERS: { value: CapaStatusFilter; label: string }[] = [
  { value: 'open', label: 'Every open CAPA' },
  { value: 'late', label: 'Late' },
  { value: 'draft', label: CAPA_STATUS_LABEL.draft },
  { value: 'approved', label: CAPA_STATUS_LABEL.approved },
  { value: 'in_progress', label: CAPA_STATUS_LABEL.in_progress },
  { value: 'done', label: CAPA_STATUS_LABEL.done },
  { value: 'effective', label: CAPA_STATUS_LABEL.effective },
  { value: 'all', label: 'Every CAPA' },
];

const SOURCE_FILTERS: { value: CapaSourceFilter; label: string }[] = [
  { value: 'all', label: 'Deviations and audits' },
  { value: 'deviation', label: 'From deviations' },
  { value: 'audit', label: 'From audits' },
];

/** 03 — every CAPA from both sources in one list, late ones first. */
export function CapaPlan({ capas }: { capas: Capa[] }) {
  const [status, setStatus] = useState<CapaStatusFilter>('open');
  const [source, setSource] = useState<CapaSourceFilter>('all');
  const shown = useMemo(() => filterCapas(capas, status, source), [capas, status, source]);
  const counts = capaCounts(capas);
  return (
    <>
      <div className="q-filters">
        <Field label="Status">
          <Select value={status} options={STATUS_FILTERS} onChange={(e) => setStatus(e.target.value as CapaStatusFilter)} />
        </Field>
        <Field label="From">
          <Select value={source} options={SOURCE_FILTERS} onChange={(e) => setSource(e.target.value as CapaSourceFilter)} />
        </Field>
      </div>
      <p className="small muted q-counts">
        {counts.open} open{counts.late > 0 ? <>, <span className="q-late">{counts.late} late</span></> : null},{' '}
        {counts.effective} effective (closed). A CAPA is opened on its deviation or audit observation above.
      </p>
      {capas.length === 0 ? (
        <Empty title="No CAPA yet.">
          <p>Every CAPA from a deviation or an audit observation is listed here, the late ones first.</p>
        </Empty>
      ) : shown.length === 0 ? (
        <Notice tone="info">No CAPA matches these choices.</Notice>
      ) : (
        <ul className="q-list">
          {shown.map((c) => (
            <CapaCard key={c.id} c={c} />
          ))}
        </ul>
      )}
    </>
  );
}
