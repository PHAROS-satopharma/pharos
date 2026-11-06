import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDate, formatDateTime } from '../../lib/format';
import { SIGNAL_OUTCOME_LABEL, SIGNAL_PRIORITY_LABEL, SIGNAL_STEP_LABEL } from '../../lib/labels';
import {
  ACTION_OUTCOMES,
  CLOSING_OUTCOMES,
  SIGNAL_PRIORITIES,
  type SignalOutcome,
  type SignalPriority,
} from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { chainOf, isStaleSignal, needsDue, nextSteps, stepDue, withSignal, type NextStep } from './signalSteps';
import type { FindingSignal, Findings, IngredientScreenData, SignalStepRow } from './types';
import '../../styles/signal-steps.css';

class StaleSignalError extends Error {
  constructor() {
    super('Someone else moved this signal a moment ago. The screen has been reloaded — please look again.');
    this.name = 'StaleSignalError';
  }
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The signal a notice belongs to (0042), under its decision: the chain Validate → Assess → Action → Closed with
 * the current stage lit, the next due day, one form for the next step, and the history. A reviewer or
 * administrator takes the step through signal_take_step, naming the stage she saw; a stale stage (PH409) reloads
 * the screen like a stale decision does. The screen's copy of the signal is replaced from finding_state().
 */
export function SignalSteps({
  issueId,
  signal,
  queryKey,
  onDone,
}: {
  issueId: string;
  signal: FindingSignal;
  queryKey: readonly unknown[];
  onDone: (text: string | null) => void;
}) {
  const { canReview } = useAuth();
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<NextStep | null>(null);
  const [comment, setComment] = useState('');
  const [priority, setPriority] = useState<SignalPriority>('medium');
  const [outcome, setOutcome] = useState<SignalOutcome | ''>('');
  const [due, setDue] = useState('');
  const today = cairoToday();

  const take = useMutation({
    mutationFn: async (s: NextStep) => {
      const wantsDue = s.needsOutcome && needsDue(outcome || null);
      const res = await supabase.rpc('signal_take_step', {
        p_signal: signal.id,
        p_step: s.step,
        // the stage she saw: the database refuses the step if the signal moved meanwhile (PH409 STALE_SIGNAL)
        p_from_stage: signal.stage,
        p_comment: comment.trim(),
        p_priority: s.needsPriority ? priority : null,
        p_outcome: s.needsOutcome ? outcome || null : null,
        p_owner: null,
        p_due: wantsDue ? due : null,
      });
      if (isStaleSignal(res.error)) throw new StaleSignalError();
      unwrap(res);
      // The signal as the database now holds it, with the due day it set.
      const states = unwrap<Findings | null>(await supabase.rpc('finding_state', { p_issues: [issueId] }));
      return states?.[issueId]?.signal ?? null;
    },
    onSuccess: (next, s) => {
      qc.setQueryData<IngredientScreenData>(queryKey, (old) => (old ? withSignal(old, issueId, next) : old));
      void qc.invalidateQueries({ queryKey: ['ingredient-screen'], refetchType: 'none' });
      setChosen(null);
      setComment('');
      setOutcome('');
      setDue('');
      onDone(`Recorded: ${SIGNAL_STEP_LABEL[s.step].toLowerCase()}.`);
    },
    onError: (e) => {
      if (!(e instanceof StaleSignalError)) return;
      setChosen(null);
      onDone(null);
      void qc.invalidateQueries({ queryKey });
    },
  });

  const next = stepDue(signal);
  const steps = nextSteps(signal.stage);
  const commentMissing = comment.trim().length === 0;
  const outcomeMissing = Boolean(chosen?.needsOutcome) && !outcome;
  const dueWanted = Boolean(chosen?.needsOutcome) && needsDue(outcome || null);
  const dueBad = dueWanted && (!DAY.test(due) || due < today);
  const blocked = commentMissing || outcomeMissing || dueBad;

  return (
    <div className="sig">
      <div className="sig-head">
        <span className="sig-ref">{signal.ref}</span>
        <span className="sig-what">
          Signal{signal.priority ? ` · ${SIGNAL_PRIORITY_LABEL[signal.priority]} priority` : ''}
        </span>
        {next ? (
          <span className={cx('sig-due', next.late && 'is-late')}>
            {next.text}
            {next.late ? (
              <>
                {' '}
                <span className="sig-late">late</span>
              </>
            ) : null}
          </span>
        ) : null}
        {signal.stage === 'closed' && signal.outcome ? (
          <span className="sig-what">{SIGNAL_OUTCOME_LABEL[signal.outcome].label}</span>
        ) : null}
        {signal.owner ? <span className="sig-owner">Owner: {signal.owner}</span> : null}
      </div>

      <ol className="sig-chain" aria-label="The signal's stages">
        {chainOf(signal.stage).map((c, i) => (
          <li key={c.stage} className={cx('sig-link', `is-${c.state}`)} aria-current={c.state === 'current' ? 'step' : undefined}>
            <span className="sig-link-n">0{i + 1}</span>
            {c.label}
          </li>
        ))}
      </ol>

      {canReview ? (
        chosen ? (
          <form
            className="sig-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!blocked) take.mutate(chosen);
            }}
          >
            <p className="sig-form-what">{chosen.label}</p>
            {chosen.needsPriority ? (
              <Field label="Priority" hint="Sets the days to assess it: 30 high, 60 medium, 90 low.">
                <Select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as SignalPriority)}
                  options={SIGNAL_PRIORITIES.map((p) => ({ value: p, label: SIGNAL_PRIORITY_LABEL[p] }))}
                />
              </Field>
            ) : null}
            {chosen.needsOutcome ? (
              <>
                <Field label="Outcome" hint={outcome ? SIGNAL_OUTCOME_LABEL[outcome].hint : 'What the assessment concluded.'}>
                  <Select
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value as SignalOutcome | '')}
                    placeholder="Choose the outcome"
                    required
                    aria-invalid={outcomeMissing || undefined}
                  >
                    <optgroup label="Closes the signal">
                      {CLOSING_OUTCOMES.map((o) => (
                        <option key={o} value={o}>
                          {SIGNAL_OUTCOME_LABEL[o].label}
                        </option>
                      ))}
                    </optgroup>
                    <optgroup label="Opens an action">
                      {ACTION_OUTCOMES.map((o) => (
                        <option key={o} value={o}>
                          {SIGNAL_OUTCOME_LABEL[o].label}
                        </option>
                      ))}
                    </optgroup>
                  </Select>
                </Field>
                {dueWanted ? (
                  <Field label="Action due" hint="Today or later.">
                    <Input
                      type="date"
                      value={due}
                      min={today}
                      onChange={(e) => setDue(e.target.value)}
                      required
                      aria-invalid={dueBad || undefined}
                    />
                  </Field>
                ) : null}
              </>
            ) : null}
            <Field label={chosen.commentLabel} hint="Kept with the signal for the record." className="sig-wide">
              <Textarea
                rows={2}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                required
                aria-invalid={commentMissing || undefined}
              />
            </Field>
            <div className="sig-form-actions">
              <Button type="submit" variant={chosen.tone === 'danger' ? 'danger' : 'primary'} busy={take.isPending} disabled={blocked}>
                Record: {chosen.label}
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  setChosen(null);
                  take.reset();
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="sig-actions">
            {steps.map((s) => (
              <Button
                key={s.step}
                variant={s.tone === 'danger' ? 'quiet' : 'secondary'}
                onClick={() => {
                  setChosen(s);
                  onDone(null);
                }}
              >
                {s.label}
              </Button>
            ))}
          </div>
        )
      ) : null}

      <History signal={signal} />

      {take.isError ? (
        take.error instanceof StaleSignalError ? (
          <Notice tone="info">{take.error.message}</Notice>
        ) : (
          <Notice tone="error">Not recorded: {errorMessage(take.error)}</Notice>
        )
      ) : null}
    </div>
  );
}

function stepWords(s: SignalStepRow): string {
  const parts = [SIGNAL_STEP_LABEL[s.step]];
  if (s.priority && (s.step === 'validated' || s.step === 'prioritised')) parts.push(`${SIGNAL_PRIORITY_LABEL[s.priority]} priority`);
  if (s.outcome && s.step === 'assessed') parts.push(SIGNAL_OUTCOME_LABEL[s.outcome].label);
  return parts.join(' · ');
}

/** Every step taken, the opening first: the evidence an inspector reads. */
function History({ signal }: { signal: FindingSignal }) {
  const n = signal.steps.length;
  return (
    <details className="sig-history">
      <summary>
        {n} {n === 1 ? 'step' : 'steps'} · opened by {signal.opened_by}, {formatDate(signal.opened_at)}
      </summary>
      <ol className="sig-steps">
        {signal.steps.map((s, i) => (
          <li key={`${s.at}-${i}`} className="sig-step">
            <span className="sig-step-what">{stepWords(s)}</span>{' '}
            <span className="sig-step-who">
              {s.person}, {formatDateTime(s.at)}
            </span>
            {s.comment ? <span className="sig-step-words">{s.comment}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
