import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { cairoToday, formatDate, formatDateTime } from '../../lib/format';
import type { IssueStatus } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { canSend, clockLine, earliestSentDay, isClockRefusal, withClockDecision, withSent, withWithdrawn } from './clock';
import { DECISION_LABEL, choicesFor, isStaleDecision, needsReason, withDecision } from './decision';
import type { AuthoritySent, Decided, Decision, FindingState, IngredientScreenData } from './types';
import '../../styles/clock.css';

class StaleDecisionError extends Error {
  constructor() {
    super('Someone else recorded a decision on this notice a moment ago. The screen has been reloaded — please look again.');
    this.name = 'StaleDecisionError';
  }
}

class ClockRefusedError extends Error {
  constructor() {
    super('The notice changed a moment ago: its decision is no longer Concerns us, or it was reported already. The screen has been reloaded — please look again.');
    this.name = 'ClockRefusedError';
  }
}

interface RecordedRow {
  to_status: IssueStatus;
  comment: string | null;
  created_at: string;
}

interface SentRow {
  id: string;
  sent_on: string;
  reference: string | null;
  note: string | null;
}

/**
 * The notice a mention is filed under: its status and latest decision, and for a reviewer or administrator the
 * decisions that can follow. A decision shows at once on every mention of the same notice on the screen; a
 * paper's buttons pass it on through onDecision, so the papers under the same notice show it too. Under
 * the decision, the five-day clock to the Egyptian Drug Authority (0041, 0050) and "Sent to the authority".
 *
 * `finding` is the notice's clock as the screen's data holds it (finding_state); the screen passes it down. The
 * cache is written here under `queryKey`, never read through a second observer: a second useQuery on the same
 * key with no queryFn would take over the query's options and break the reload after a refusal.
 */
export function DecisionButtons({
  mention,
  queryKey,
  finding,
  onDecision,
}: {
  mention: Decided;
  queryKey: readonly unknown[];
  finding: FindingState | null;
  onDecision?: (issueId: string, d: Decision) => void;
}) {
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
      const decision: Decision = {
        to_status: row.to_status,
        person: person?.full_name ?? 'You',
        at: row.created_at,
        comment: row.comment,
      };
      qc.setQueryData<IngredientScreenData>(queryKey, (old) =>
        old ? withClockDecision(withDecision(old, issueId, decision), issueId, row.to_status, cairoToday()) : old,
      );
      onDecision?.(issueId, decision);
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
  const line = clockLine(finding);

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
        {line && finding ? <span className={cx('clock', `clock-${finding.clock}`)}>{line}</span> : null}
      </div>
      {d?.comment ? <p className="scr-decision-why">{d.comment}</p> : null}
      {finding?.clock === 'sent' && finding.sent ? (
        <>
          <p className="clock-sent-by">Recorded by {finding.sent.person}</p>
          {finding.sent.note ? <p className="clock-sent-note">{finding.sent.note}</p> : null}
        </>
      ) : null}

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

      {canReview && finding && !changing ? (
        <AuthorityActions issueId={issueId} finding={finding} queryKey={queryKey} onDone={setDone} />
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

/** "Sent to the authority" while the clock runs or is late; "Withdraw" once it was sent. Reviewers and
 *  administrators only (the caller checks). */
function AuthorityActions({
  issueId,
  finding,
  queryKey,
  onDone,
}: {
  issueId: string;
  finding: FindingState;
  queryKey: readonly unknown[];
  onDone: (text: string | null) => void;
}) {
  const { person } = useAuth();
  const qc = useQueryClient();
  const [mode, setMode] = useState<'closed' | 'sent' | 'withdraw'>('closed');
  const [sentOn, setSentOn] = useState(() => cairoToday());
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('');
  const [why, setWhy] = useState('');
  const today = cairoToday();

  const afterChange = () => {
    void qc.invalidateQueries({ queryKey: ['ingredient-screen'], refetchType: 'none' });
    setMode('closed');
  };

  const send = useMutation({
    mutationFn: async () => {
      if (!person) throw new Error('Sign in first.');
      // The database stamps the time, names the decision it answers and refuses a notice whose latest decision
      // is not Concerns us (PH409 NO_CONCERN) or that was reported already (PH409 ALREADY_SENT).
      const res = await supabase
        .from('authority_report')
        .insert({
          issue_id: issueId,
          sent_on: sentOn,
          reference: reference.trim() || null,
          note: note.trim() || null,
          person_id: person.id,
        })
        .select('id,sent_on,reference,note')
        .single();
      if (isClockRefusal(res.error)) throw new ClockRefusedError();
      return unwrap<SentRow>(res);
    },
    onSuccess: (row) => {
      const sent: AuthoritySent = {
        id: row.id,
        on: row.sent_on,
        reference: row.reference,
        person: person?.full_name ?? 'You',
        note: row.note,
      };
      qc.setQueryData<IngredientScreenData>(queryKey, (old) => (old ? withSent(old, issueId, sent) : old));
      afterChange();
      setReference('');
      setNote('');
      onDone('Recorded: sent to the authority.');
    },
    onError: (e) => {
      if (e instanceof ClockRefusedError) {
        setMode('closed');
        void qc.invalidateQueries({ queryKey });
      }
    },
  });

  const withdraw = useMutation({
    mutationFn: async () => {
      if (!finding.sent) throw new Error('Nothing to withdraw.');
      unwrap(await supabase.rpc('withdraw_authority_report', { p_id: finding.sent.id, p_reason: why.trim() }));
    },
    onSuccess: () => {
      qc.setQueryData<IngredientScreenData>(queryKey, (old) => (old ? withWithdrawn(old, issueId, today) : old));
      afterChange();
      setWhy('');
      onDone('The report was withdrawn; the clock runs again.');
    },
  });

  // Between the day PHAROS first showed the notice and today: the database refuses anything else (22023).
  const earliest = earliestSentDay(finding);
  const dateBad = !/^\d{4}-\d{2}-\d{2}$/.test(sentOn) || sentOn > today || (earliest !== undefined && sentOn < earliest);

  if (mode === 'sent') {
    return (
      <form
        className="clock-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!dateBad) send.mutate();
        }}
      >
        <p className="clock-form-what">Sent to the Egyptian Drug Authority</p>
        <Field
          label="Day sent"
          hint={earliest ? `From ${formatDate(earliest)}, the day PHAROS first showed the notice, to today.` : 'Today or earlier.'}
        >
          <Input
            type="date"
            value={sentOn}
            min={earliest}
            max={today}
            onChange={(e) => setSentOn(e.target.value)}
            required
            aria-invalid={dateBad || undefined}
          />
        </Field>
        <Field label="Reference (optional)" hint="The authority's or our file number.">
          <Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={200} />
        </Field>
        <Field label="Note (optional)" className="clock-wide">
          <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="clock-form-actions">
          <Button type="submit" variant="primary" busy={send.isPending} disabled={dateBad}>
            Record: sent to the authority
          </Button>
          <Button variant="quiet" onClick={() => setMode('closed')}>
            Cancel
          </Button>
        </div>
        {send.isError ? (
          send.error instanceof ClockRefusedError ? (
            <Notice tone="info">{send.error.message}</Notice>
          ) : (
            <Notice tone="error">Not recorded: {errorMessage(send.error)}</Notice>
          )
        ) : null}
      </form>
    );
  }

  if (mode === 'withdraw') {
    const whyMissing = why.trim().length === 0;
    return (
      <form
        className="clock-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!whyMissing) withdraw.mutate();
        }}
      >
        <p className="clock-form-what">Withdraw the report to the authority</p>
        <Field label="Why it is withdrawn (required)" hint="The report stays on record as withdrawn." className="clock-wide">
          <Textarea rows={2} value={why} onChange={(e) => setWhy(e.target.value)} required aria-invalid={whyMissing || undefined} />
        </Field>
        <div className="clock-form-actions">
          <Button type="submit" variant="danger" busy={withdraw.isPending} disabled={whyMissing}>
            Withdraw
          </Button>
          <Button variant="quiet" onClick={() => setMode('closed')}>
            Cancel
          </Button>
        </div>
        {withdraw.isError ? <Notice tone="error">Not withdrawn: {errorMessage(withdraw.error)}</Notice> : null}
      </form>
    );
  }

  if (canSend(finding)) {
    return (
      <div className="clock-actions">
        <Button
          variant="secondary"
          onClick={() => {
            setSentOn(cairoToday());
            setMode('sent');
            onDone(null);
          }}
        >
          Sent to the authority
        </Button>
      </div>
    );
  }
  if (finding.clock === 'sent' && finding.sent) {
    return (
      <div className="clock-actions">
        <Button
          variant="quiet"
          size="sm"
          onClick={() => {
            setMode('withdraw');
            onDone(null);
          }}
        >
          Withdraw the report
        </Button>
      </div>
    );
  }
  return null;
}
