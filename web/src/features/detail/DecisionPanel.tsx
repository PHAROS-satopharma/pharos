import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { STATUS_LABEL } from '../../lib/labels';
import type { IssueRow, IssueStatus } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Textarea } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { StatusPill } from '../../ui/Tag';
import { cx } from '../../ui/cx';

const STEPS: { key: string; label: string; statuses: IssueStatus[] }[] = [
  { key: 'new', label: 'New', statuses: ['new'] },
  { key: 'reviewed', label: 'Reviewed', statuses: ['reviewed'] },
  { key: 'decided', label: 'Relevant / Not relevant', statuses: ['relevant', 'not_relevant'] },
];

const CHOICES: { to: IssueStatus; label: string; hint: string }[] = [
  { to: 'reviewed', label: 'Reviewed', hint: 'Read, decision still to come.' },
  { to: 'relevant', label: 'Relevant', hint: 'It concerns our products and needs action or follow-up.' },
  { to: 'not_relevant', label: 'Not relevant', hint: 'It does not concern our products. Say why.' },
];

/** The database refused the decision: the notice's status changed since this page read it (SQLSTATE PH409). */
class StaleDecisionError extends Error {
  constructor() {
    super('Someone else recorded a decision on this notice a moment ago. It has been reloaded — please look again.');
    this.name = 'StaleDecisionError';
  }
}

function isStaleDecision(error: { code?: string; message?: string } | null): boolean {
  if (!error) return false;
  return error.code === 'PH409' || (error.message ?? '').startsWith('STALE_DECISION');
}

export function DecisionPanel({ issue }: { issue: IssueRow }) {
  const { canReview, person } = useAuth();
  const qc = useQueryClient();
  const [target, setTarget] = useState<IssueStatus | null>(null);
  const [comment, setComment] = useState('');
  const [done, setDone] = useState<string | null>(null);

  const currentStep = STEPS.findIndex((s) => s.statuses.includes(issue.status));
  const needsComment = target === 'not_relevant';
  const commentMissing = needsComment && comment.trim().length === 0;

  const save = useMutation({
    mutationFn: async () => {
      if (!target || !person) throw new Error('Choose a decision first.');
      // The database stamps the time and checks from_status against the notice's status at this moment.
      const res = await supabase.from('review_event').insert({
        issue_id: issue.id,
        from_status: issue.status,
        to_status: target,
        comment: comment.trim() || null,
        person_id: person.id,
      });
      if (isStaleDecision(res.error)) throw new StaleDecisionError();
      unwrap<null>(res);
    },
    onError: async (e) => {
      if (!(e instanceof StaleDecisionError)) return;
      // Show the notice as it is now; the comment stays typed in case it still applies.
      setTarget(null);
      setDone(null);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['issue', issue.id] }),
        qc.invalidateQueries({ queryKey: ['issue-reviews', issue.id] }),
        qc.invalidateQueries({ queryKey: ['issues'] }),
      ]);
    },
    onSuccess: async () => {
      setDone(`Recorded as ${STATUS_LABEL[target ?? issue.status]}.`);
      setTarget(null);
      setComment('');
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['issue', issue.id] }),
        qc.invalidateQueries({ queryKey: ['issue-reviews', issue.id] }),
        qc.invalidateQueries({ queryKey: ['issues'] }),
      ]);
    },
  });

  return (
    <section className="panel decision" aria-labelledby="decision-title">
      <div className="panel-head">
        <h2 id="decision-title" className="panel-title">
          Decision
        </h2>
        <StatusPill status={issue.status} />
      </div>

      <ol className="steps" aria-label="Review steps">
        {STEPS.map((s, i) => (
          <li
            key={s.key}
            className={cx('step', i < currentStep && 'is-done', i === currentStep && 'is-current')}
            aria-current={i === currentStep ? 'step' : undefined}
          >
            {s.label}
          </li>
        ))}
      </ol>

      {!canReview ? (
        <p className="soft small">
          You can read every decision. Recording one needs a reviewer or administrator account.
        </p>
      ) : (
        <form
          className="decision-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!commentMissing && target) save.mutate();
          }}
        >
          <fieldset className="choices">
            <legend className="field-label">Record a decision</legend>
            {CHOICES.filter((c) => c.to !== issue.status).map((c) => (
              <label key={c.to} className={cx('choice', `choice-${c.to}`, target === c.to && 'is-selected')}>
                <input
                  type="radio"
                  name="decision"
                  value={c.to}
                  checked={target === c.to}
                  onChange={() => {
                    setTarget(c.to);
                    setDone(null);
                  }}
                />
                <span className="choice-text">
                  <span className="choice-label">{c.label}</span>
                  <span className="choice-hint">{c.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          {target ? (
            <Field
              label={needsComment ? 'Why it is not relevant (required)' : 'Comment (optional)'}
              hint="Kept with the decision for the record. It is never sent by Telegram."
            >
              <Textarea
                rows={3}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                aria-invalid={commentMissing || undefined}
                required={needsComment}
              />
            </Field>
          ) : null}

          {save.isError ? (
            save.error instanceof StaleDecisionError ? (
              <Notice tone="info">{save.error.message}</Notice>
            ) : (
              <Notice tone="error">Not recorded: {errorMessage(save.error)}</Notice>
            )
          ) : null}
          {done ? <Notice tone="ok">{done}</Notice> : null}

          <Button
            type="submit"
            variant="primary"
            busy={save.isPending}
            disabled={!target || commentMissing}
            className="btn-block"
          >
            {target ? `Record: ${STATUS_LABEL[target]}` : 'Choose a decision'}
          </Button>
          <p className="soft small">Recorded as {person?.full_name}. Decisions cannot be edited afterwards, only followed by a new one.</p>
        </form>
      )}
    </section>
  );
}
