import { useState } from 'react';
import { StaleSignalError, useOwners, useTakeStep } from './queries';
import { errorMessage } from '../../lib/api';
import { cairoToday } from '../../lib/format';
import { SIGNAL_OUTCOME_LABEL, SIGNAL_PRIORITY_LABEL, SIGNAL_STEP_LABEL } from '../../lib/labels';
import { stepsFor } from '../../lib/signals';
import {
  ACTION_OUTCOMES,
  CLOSING_OUTCOMES,
  SIGNAL_PRIORITIES,
  type SignalOutcome,
  type SignalPriority,
  type SignalRow,
  type SignalStep,
} from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';

const STEP_HINT: Partial<Record<SignalStep, string>> = {
  validated: 'The evidence points to a new risk, or a change to a known one. It moves to assessment.',
  not_validated: 'The evidence does not support a signal. The signal closes with the reason.',
  assessed: 'Record the conclusion and its outcome. An outcome that needs action opens it with a due date.',
  action_done: 'The action is complete. Give its reference (variation, RMP version, letter date).',
  prioritised: 'Change the priority. The assessment due date follows it.',
  assigned: 'Choose who owns the signal from now on.',
  reopened: 'New information. The signal goes back to assessment.',
  note: 'Add information for the record without moving the signal.',
};

const COMMENT_LABEL: Partial<Record<SignalStep, string>> = {
  validated: 'Why it is a signal (required)',
  not_validated: 'Why it is not a signal (required)',
  assessed: 'The conclusion of the assessment (required)',
  action_done: 'What was done, with its reference (required)',
  prioritised: 'Why the priority changes (required)',
  reopened: 'Why it is reopened (required)',
  note: 'The note (required)',
  assigned: 'Comment (optional)',
};

export function StepForm({ signal }: { signal: SignalRow }) {
  const take = useTakeStep(signal.id);
  const owners = useOwners();
  const [step, setStep] = useState<SignalStep | null>(null);
  const [comment, setComment] = useState('');
  const [priority, setPriority] = useState<SignalPriority | ''>('');
  const [outcome, setOutcome] = useState<SignalOutcome | ''>('');
  const [owner, setOwner] = useState('');
  const [due, setDue] = useState('');
  const [done, setDone] = useState<string | null>(null);

  const needsAction = outcome !== '' && ACTION_OUTCOMES.includes(outcome);
  const missing =
    !step ||
    (step !== 'assigned' && comment.trim() === '') ||
    ((step === 'validated' || step === 'prioritised') && priority === '') ||
    (step === 'prioritised' && priority === signal.priority) ||
    (step === 'assigned' && (owner === '' || owner === signal.owner_id)) ||
    (step === 'assessed' && (outcome === '' || (needsAction && due === '')));

  function choose(s: SignalStep) {
    setStep(s);
    setDone(null);
    take.reset();
    setPriority(s === 'prioritised' || s === 'validated' ? (signal.priority ?? '') : '');
  }

  return (
    <form
      className="decision-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (missing || !step) return;
        const chosen = step;
        take.mutate(
          {
            step: chosen,
            fromStage: signal.stage,
            comment,
            priority: priority || null,
            outcome: chosen === 'assessed' ? outcome || null : null,
            owner: chosen === 'assigned' ? owner : null,
            due: chosen === 'assessed' && needsAction ? due : null,
          },
          {
            onSuccess: () => {
              setDone(`Recorded: ${SIGNAL_STEP_LABEL[chosen]}.`);
              setStep(null);
              setComment('');
              setOutcome('');
              setOwner('');
              setDue('');
            },
            onError: (err) => {
              if (err instanceof StaleSignalError) setStep(null);
            },
          },
        );
      }}
    >
      <fieldset className="choices">
        <legend className="field-label">Next step</legend>
        {stepsFor(signal.stage).map((s) => (
          <label key={s} className={cx('choice', step === s && 'is-selected')}>
            <input type="radio" name="signal-step" value={s} checked={step === s} onChange={() => choose(s)} />
            <span className="choice-text">
              <span className="choice-label">{SIGNAL_STEP_LABEL[s]}</span>
              <span className="choice-hint">{STEP_HINT[s]}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {step === 'validated' || step === 'prioritised' ? (
        <Field label="Priority">
          <Select value={priority} onChange={(e) => setPriority(e.target.value as SignalPriority | '')} placeholder="Choose">
            {SIGNAL_PRIORITIES.filter((p) => step !== 'prioritised' || p !== signal.priority).map((p) => (
              <option key={p} value={p}>
                {SIGNAL_PRIORITY_LABEL[p]}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}

      {step === 'assigned' ? (
        <Field label="Owner">
          <Select value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Choose a person">
            {(owners.data ?? [])
              .filter((p) => p.id !== signal.owner_id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.full_name}
                </option>
              ))}
          </Select>
        </Field>
      ) : null}

      {step === 'assessed' ? (
        <>
          <Field label="Outcome">
            <Select value={outcome} onChange={(e) => setOutcome(e.target.value as SignalOutcome | '')} placeholder="Choose">
              <optgroup label="Needs action">
                {ACTION_OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {SIGNAL_OUTCOME_LABEL[o].label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Closes the signal">
                {CLOSING_OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {SIGNAL_OUTCOME_LABEL[o].label}
                  </option>
                ))}
              </optgroup>
            </Select>
          </Field>
          {outcome ? <p className="soft small">{SIGNAL_OUTCOME_LABEL[outcome].hint}</p> : null}
          {needsAction ? (
            <Field label="Action due by" hint="A Cairo calendar day, from today on.">
              <Input type="date" min={cairoToday()} value={due} onChange={(e) => setDue(e.target.value)} required />
            </Field>
          ) : null}
        </>
      ) : null}

      {step ? (
        <Field label={COMMENT_LABEL[step] ?? 'Comment'} hint="Kept with the step for the record. It cannot be edited afterwards.">
          <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} required={step !== 'assigned'} />
        </Field>
      ) : null}

      {take.isError ? (
        take.error instanceof StaleSignalError ? (
          <Notice tone="info">{take.error.message}</Notice>
        ) : (
          <Notice tone="error">Not recorded: {errorMessage(take.error)}</Notice>
        )
      ) : null}
      {done ? <Notice tone="ok">{done}</Notice> : null}

      <Button type="submit" variant="primary" busy={take.isPending} disabled={missing} className="btn-block">
        {step ? `Record: ${SIGNAL_STEP_LABEL[step]}` : 'Choose a step'}
      </Button>
    </form>
  );
}
