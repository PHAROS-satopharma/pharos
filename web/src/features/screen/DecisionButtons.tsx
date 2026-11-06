import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDateTime } from '../../lib/format';
import type { IssueStatus } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Textarea } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { DECISION_LABEL, choicesFor, isStaleDecision, needsReason, withDecision } from './decision';
import type { IngredientScreenData, Mention } from './types';

class StaleDecisionError extends Error {
  constructor() {
    super('Someone else recorded a decision on this notice a moment ago. The screen has been reloaded — please look again.');
    this.name = 'StaleDecisionError';
  }
}

interface RecordedRow {
  to_status: IssueStatus;
  comment: string | null;
  created_at: string;
}

/**
 * The notice a mention is filed under: its status and latest decision, and for a reviewer or administrator the
 * decisions that can follow. A decision shows at once on every mention of the same notice on the screen.
 */
export function DecisionButtons({ mention, queryKey }: { mention: Mention; queryKey: readonly unknown[] }) {
  const { canReview, person } = useAuth();
  const qc = useQueryClient();
  const [changing, setChanging] = useState(false);
  const [target, setTarget] = useState<IssueStatus | null>(null);
  const [reason, setReason] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const issueId = mention.issue_id;
  const status = mention.issue_status;

  const save = useMutation({
    mutationFn: async (to: IssueStatus) => {
      if (!person || !issueId || !status) throw new Error('Choose a decision first.');
      // The database stamps the time and checks from_status against the notice's status at this moment.
      const res = await supabase
        .from('review_event')
        .insert({
          issue_id: issueId,
          from_status: status,
          to_status: to,
          comment: reason.trim() || null,
          person_id: person.id,
        })
        .select('to_status,comment,created_at')
        .single();
      if (isStaleDecision(res.error)) throw new StaleDecisionError();
      return unwrap<RecordedRow>(res);
    },
    onSuccess: (row) => {
      if (!issueId) return;
      // Other ranges and screens read again when next opened; this one shows the decision now.
      void qc.invalidateQueries({ queryKey: ['ingredient-screen'], refetchType: 'none' });
      qc.setQueryData<IngredientScreenData>(queryKey, (old) =>
        old
          ? withDecision(old, issueId, {
              to_status: row.to_status,
              person: person?.full_name ?? 'You',
              at: row.created_at,
              comment: row.comment,
            })
          : old,
      );
      void qc.invalidateQueries({ queryKey: ['issues'] });
      void qc.invalidateQueries({ queryKey: ['issue', issueId] });
      void qc.invalidateQueries({ queryKey: ['issue-reviews', issueId] });
      setDone(`Recorded: ${DECISION_LABEL[row.to_status]}.`);
      setTarget(null);
      setReason('');
      setChanging(false);
    },
    onError: (e) => {
      if (!(e instanceof StaleDecisionError)) return;
      // Show the notice as it is now; the reason stays typed in case it still applies.
      setTarget(null);
      setDone(null);
      void qc.invalidateQueries({ queryKey });
    },
  });

  if (!issueId || !status) return null;

  const open = status === 'new' || status === 'reviewed' || changing;
  const reasonMissing = needsReason(target) && reason.trim().length === 0;
  const d = mention.decision;

  return (
    <div className="scr-decision">
      <div className="scr-decision-now">
        <span className={cx('status', `status-${status}`)}>
          <span className="status-marker" aria-hidden />
          {DECISION_LABEL[status]}
        </span>
        {d ? (
          <span className="scr-decision-who">
            {d.person}, {formatDateTime(d.at)}
          </span>
        ) : null}
      </div>
      {d?.comment ? <p className="scr-decision-why">{d.comment}</p> : null}

      {canReview ? (
        open ? (
          <form
            className="scr-decide"
            onSubmit={(e) => {
              e.preventDefault();
              if (target && !reasonMissing) save.mutate(target);
            }}
          >
            <div className="scr-choices" role="group" aria-label="Record a decision">
              {choicesFor(status).map((c) => (
                <button
                  key={c.to}
                  type="button"
                  className={cx('scr-choice', `scr-choice-${c.to}`, target === c.to && 'is-selected')}
                  aria-pressed={target === c.to}
                  title={c.hint}
                  onClick={() => {
                    setTarget(target === c.to ? null : c.to);
                    setDone(null);
                  }}
                >
                  {c.label}
                </button>
              ))}
            </div>
            {target ? (
              <>
                <Field
                  label={needsReason(target) ? "Why it doesn't concern us (required)" : 'Comment (optional)'}
                  hint="Kept with the decision for the record."
                >
                  <Textarea
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    aria-invalid={reasonMissing || undefined}
                    required={needsReason(target)}
                  />
                </Field>
                <div className="scr-decide-actions">
                  <Button type="submit" variant="primary" busy={save.isPending} disabled={reasonMissing}>
                    Record: {DECISION_LABEL[target]}
                  </Button>
                  {changing ? (
                    <Button
                      variant="quiet"
                      onClick={() => {
                        setChanging(false);
                        setTarget(null);
                      }}
                    >
                      Cancel
                    </Button>
                  ) : null}
                </div>
              </>
            ) : changing ? (
              <Button variant="quiet" size="sm" onClick={() => setChanging(false)}>
                Cancel
              </Button>
            ) : null}
          </form>
        ) : (
          <Button
            size="sm"
            variant="quiet"
            className="scr-change"
            onClick={() => {
              setChanging(true);
              setDone(null);
            }}
          >
            Change
          </Button>
        )
      ) : null}

      {save.isError ? (
        save.error instanceof StaleDecisionError ? (
          <Notice tone="info">{save.error.message}</Notice>
        ) : (
          <Notice tone="error">Not recorded: {errorMessage(save.error)}</Notice>
        )
      ) : null}
      {done ? <Notice tone="ok">{done}</Notice> : null}
    </div>
  );
}
