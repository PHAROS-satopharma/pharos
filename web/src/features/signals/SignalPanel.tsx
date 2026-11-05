import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useIssueSignal, useLinkToSignal, useOpenSignal, useSignals } from './queries';
import { DueNote, StagePill } from './SignalUi';
import { useIngredientList } from '../people/useIngredientList';
import { errorMessage } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import type { IssueRow } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';

type Mode = 'new' | 'existing';

/** On a notice: the signal it belongs to, or — for a Relevant notice — a way to open one or join one. */
export function SignalPanel({ issue }: { issue: IssueRow }) {
  const linked = useIssueSignal(issue.id);
  const { canReview } = useAuth();

  if (linked.isPending) {
    return (
      <section className="panel">
        <h2 className="panel-title">Signal</h2>
        <Loading />
      </section>
    );
  }
  if (linked.isError) {
    return (
      <section className="panel">
        <h2 className="panel-title">Signal</h2>
        <ErrorNote error={linked.error} onRetry={() => void linked.refetch()} />
      </section>
    );
  }
  const s = linked.data;
  if (s) {
    return (
      <section className="panel" aria-labelledby="signal-panel-title">
        <div className="panel-head">
          <h2 id="signal-panel-title" className="panel-title">
            Signal
          </h2>
          <StagePill stage={s.stage} />
        </div>
        <div className="signal-link">
          <Link to={`/signals/${s.id}`} className="title-link" dir="auto">
            {s.title}
          </Link>
          <span className="title-meta">
            <span className="mono">{s.ref}</span>
            <DueNote signal={s} />
          </span>
        </div>
      </section>
    );
  }
  if (issue.status !== 'relevant') return null;
  return (
    <section className="panel" aria-labelledby="signal-panel-title">
      <h2 id="signal-panel-title" className="panel-title">
        Signal
      </h2>
      {canReview ? (
        <OpenOrJoin issue={issue} />
      ) : (
        <p className="soft small">This notice is Relevant and no signal has been opened for it yet.</p>
      )}
    </section>
  );
}

function OpenOrJoin({ issue }: { issue: IssueRow }) {
  const ingredients = useIngredientList();
  const open = useSignals('open');
  const openSignal = useOpenSignal(issue.id);
  const join = useLinkToSignal(issue.id);
  const [mode, setMode] = useState<Mode>('new');
  const [title, setTitle] = useState(issue.title);
  // The notice's own ingredient when it names exactly one; otherwise the reviewer chooses.
  const only = issue.ingredients?.length === 1 ? issue.ingredients[0] : null;
  const [ingredient, setIngredient] = useState<string | null>(null);
  const [signalId, setSignalId] = useState('');
  const [comment, setComment] = useState('');

  const ingredientId =
    ingredient ?? (only ? ((ingredients.data ?? []).find((i) => i.inn_en === only)?.id ?? '') : '');
  const busy = openSignal.isPending || join.isPending;
  const error = openSignal.error ?? join.error;

  return (
    <form
      className="decision-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (mode === 'new' && title.trim()) {
          openSignal.mutate({ title, ingredient: ingredientId || null, comment });
        } else if (mode === 'existing' && signalId) {
          join.mutate({ signalId, comment });
        }
      }}
    >
      <p className="soft small">
        This notice is Relevant. Open a signal to validate and assess it, or add it to a signal already open on the
        same topic.
      </p>
      <div className="segmented" role="group" aria-label="New or existing signal">
        <button
          type="button"
          className={cx('segment', mode === 'new' && 'is-active')}
          aria-pressed={mode === 'new'}
          onClick={() => setMode('new')}
        >
          Open a signal
        </button>
        <button
          type="button"
          className={cx('segment', mode === 'existing' && 'is-active')}
          aria-pressed={mode === 'existing'}
          onClick={() => setMode('existing')}
        >
          Add to an open one
        </button>
      </div>

      {mode === 'new' ? (
        <>
          <Field label="Signal title" hint="The safety topic, for example “Acute kidney injury”.">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} required dir="auto" />
          </Field>
          <Field label="Ingredient">
            <Select
              value={ingredientId}
              onChange={(e) => setIngredient(e.target.value)}
              placeholder="None (class-wide)"
              options={(ingredients.data ?? []).map((i) => ({ value: i.id, label: i.inn_en }))}
            />
          </Field>
        </>
      ) : (
        <Field label="Open signal">
          <Select
            value={signalId}
            onChange={(e) => setSignalId(e.target.value)}
            placeholder={open.isPending ? 'Reading the signals…' : (open.data ?? []).length === 0 ? 'No open signal' : 'Choose'}
            options={(open.data ?? []).map((s) => ({ value: s.id, label: `${s.ref} · ${s.title}` }))}
          />
        </Field>
      )}

      <Field label="Comment (optional)" hint="Kept with the step for the record.">
        <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>

      {error ? <Notice tone="error">Not recorded: {errorMessage(error)}</Notice> : null}

      <Button
        type="submit"
        variant="primary"
        busy={busy}
        disabled={mode === 'new' ? !title.trim() : !signalId}
        className="btn-block"
      >
        {mode === 'new' ? 'Open the signal' : 'Add to the signal'}
      </Button>
    </form>
  );
}
