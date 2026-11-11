import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { cairoToday, formatDateTime } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { type DeviationProposal, type HistoryRow, type QualityState, type Step, historyWords, isStale } from './quality';

export const QUALITY_KEY = ['quality-state'] as const;

/** Everything the tab shows, in one read (quality_state(), 0107). */
export function useQuality() {
  return useQuery({
    queryKey: QUALITY_KEY,
    queryFn: async () => unwrap<QualityState>(await supabase.rpc('quality_state')),
  });
}

/**
 * The proposed deviations (deviation_proposals(), 0108). Under the tab's key, so every write reads them again.
 * Before 0108 is applied the read fails: the tab then shows none, never an error.
 */
export function useProposals() {
  return useQuery({
    queryKey: [...QUALITY_KEY, 'proposals'],
    retry: false,
    queryFn: async () => unwrap<DeviationProposal[] | null>(await supabase.rpc('deviation_proposals')) ?? [],
  });
}

export interface PersonOption {
  id: string;
  full_name: string;
}

/** The active people, for an owner or a stakeholder (person_directory: names only). */
export function usePeople() {
  return useQuery({
    queryKey: ['quality-people'],
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<PersonOption[] | null>(
        await supabase.from('person_directory').select('id,full_name').eq('active', true).order('full_name'),
      ) ?? [],
  });
}

export class StaleError extends Error {
  constructor() {
    super('Someone else changed this record a moment ago. It has been reloaded — please look again.');
    this.name = 'StaleError';
  }
}

/** Calls one of the quality functions; afterwards the tab is read again (a stale write reloads it too). */
export function useWrite<T = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ fn, args }: { fn: string; args: Record<string, unknown> }): Promise<T> => {
      const res = await supabase.rpc(fn, args);
      if (isStale(res.error)) throw new StaleError();
      return unwrap<T>(res);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: QUALITY_KEY }),
  });
}

/** The error of a write, in her words. */
export function WriteError({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof StaleError) return <Notice tone="info">{error.message}</Notice>;
  return <Notice tone="error">Not recorded: {errorMessage(error)}</Notice>;
}

export const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The next steps of a record as buttons; choosing one opens its form (a comment where the step is a judgement,
 * the day, the evidence). `take` runs the step with what she wrote.
 */
export function StepButtons<To extends string>({
  steps,
  busy,
  take,
  error,
  dayLabel = 'Day',
}: {
  steps: Step<To>[];
  busy: boolean;
  take: (s: Step<To>, v: { comment: string; day: string; evidence: string }) => void;
  error: unknown;
  dayLabel?: string;
}) {
  const [chosen, setChosen] = useState<Step<To> | null>(null);
  const [comment, setComment] = useState('');
  const [day, setDay] = useState('');
  const [evidence, setEvidence] = useState('');
  const today = cairoToday();
  if (steps.length === 0) return null;

  if (!chosen) {
    return (
      <div className="q-steps">
        {steps.map((s) => (
          <div key={`${s.to}-${String(s.satisfactory)}`} className="q-step-choice">
            <Button
              variant={s.tone === 'danger' ? 'quiet' : 'primary'}
              disabled={Boolean(s.blocked)}
              onClick={() => {
                setChosen(s);
                setComment('');
                setDay(s.needsDay || s.needsEvidence ? today : '');
                setEvidence('');
              }}
            >
              {s.label}
            </Button>
            {s.blocked ? <span className="q-blocked">{s.blocked}</span> : null}
          </div>
        ))}
        <WriteError error={error} />
      </div>
    );
  }

  const commentMissing = chosen.needsComment && comment.trim() === '';
  const dayBad = Boolean(chosen.needsDay || chosen.needsEvidence) && (!DAY.test(day) || day > today);
  const evidenceMissing = Boolean(chosen.needsEvidence) && evidence.trim() === '';
  const blocked = commentMissing || dayBad || evidenceMissing;
  return (
    <form
      className="q-form q-step-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        take(chosen, { comment: comment.trim(), day, evidence: evidence.trim() });
        setChosen(null);
      }}
    >
      <p className="q-form-what">{chosen.label}</p>
      {chosen.needsEvidence ? (
        <Field label="Evidence" hint="What was done: a document reference or a link." className="q-wide">
          <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} required />
        </Field>
      ) : null}
      {chosen.needsDay || chosen.needsEvidence ? (
        <Field label={chosen.needsEvidence ? 'Done on' : dayLabel} hint="Today or earlier.">
          <Input type="date" value={day} max={today} onChange={(e) => setDay(e.target.value)} required />
        </Field>
      ) : null}
      <Field
        label={chosen.needsComment ? 'Comment (required)' : 'Comment (optional)'}
        hint="Kept in the history for the record."
        className="q-wide"
      >
        <Textarea
          rows={2}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          required={chosen.needsComment}
          aria-invalid={commentMissing || undefined}
        />
      </Field>
      <div className="button-row q-wide">
        <Button type="submit" variant={chosen.tone === 'danger' ? 'danger' : 'primary'} busy={busy} disabled={blocked}>
          Record: {chosen.label}
        </Button>
        <Button variant="quiet" onClick={() => setChosen(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Every step taken, oldest first: the evidence an inspector reads. Never changed. */
export function History({ rows }: { rows: HistoryRow[] }) {
  const n = rows.length;
  return (
    <details className="q-history">
      <summary>
        History · {n} {n === 1 ? 'entry' : 'entries'}
      </summary>
      <ol className="q-history-list">
        {rows.map((h, i) => (
          <li key={`${h.at}-${i}`}>
            <span className="q-history-what">{historyWords(h)}</span>{' '}
            <span className="q-history-who">
              {h.person ?? 'a member of the team'}, {formatDateTime(h.at)}
            </span>
            {h.comment ? <span className="q-history-words">{h.comment}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

/** One line of a record: a micro label and its value. */
export function Fact({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={cx('q-fact', wide && 'q-wide')}>
      <dt className="micro">{label}</dt>
      <dd>{children ?? '—'}</dd>
    </div>
  );
}

/** A person of PHAROS, or someone outside it by name. */
export function OwnerFields({
  label,
  personId,
  other,
  setPersonId,
  setOther,
}: {
  label: string;
  personId: string;
  other: string;
  setPersonId: (v: string) => void;
  setOther: (v: string) => void;
}) {
  const people = usePeople();
  return (
    <>
      <Field label={label}>
        <Select
          value={personId}
          placeholder="Someone outside PHAROS"
          options={(people.data ?? []).map((p) => ({ value: p.id, label: p.full_name }))}
          onChange={(e) => setPersonId(e.target.value)}
        />
      </Field>
      {personId === '' ? (
        <Field label="Outside PHAROS: name and department">
          <Input value={other} onChange={(e) => setOther(e.target.value)} placeholder="e.g. Head of Regulatory Affairs" />
        </Field>
      ) : null}
    </>
  );
}
