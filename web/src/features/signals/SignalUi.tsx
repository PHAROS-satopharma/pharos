import { SIGNAL_PRIORITY_LABEL, SIGNAL_STAGE_LABEL } from '../../lib/labels';
import { cairoToday } from '../../lib/format';
import { dueWords } from '../../lib/signals';
import { SIGNAL_STAGES, type SignalPriority, type SignalRow, type SignalStage } from '../../lib/types';
import { Tag } from '../../ui/Tag';
import { cx } from '../../ui/cx';

/** The stage of a signal, as the review status is shown: a square marker, then the word. */
export function StagePill({ stage }: { stage: SignalStage }) {
  return (
    <span className={cx('status', `signal-stage-${stage}`)}>
      <span className="status-marker" aria-hidden />
      {SIGNAL_STAGE_LABEL[stage]}
    </span>
  );
}

export function PriorityTag({ priority }: { priority: SignalPriority | null }) {
  if (!priority) return <span className="soft small">Not set</span>;
  return <Tag tone={priority === 'high' ? 'danger' : priority === 'medium' ? 'warning' : 'quiet'}>{SIGNAL_PRIORITY_LABEL[priority]}</Tag>;
}

/** When the current stage is due, in Cairo days; a closed signal says so instead. */
export function DueNote({ signal }: { signal: SignalRow }) {
  if (signal.stage === 'closed') return <span className="soft small">Closed</span>;
  const words = dueWords(signal.next_due, cairoToday());
  return signal.overdue ? <Tag tone="danger">{words}</Tag> : <span className="small">{words}</span>;
}

/** The four signal stages, numbered, on a rule that fills as the signal moves on. */
export function StageSteps({ stage }: { stage: SignalStage }) {
  const current = SIGNAL_STAGES.indexOf(stage);
  return (
    <ol className="steps steps-4" aria-label="Signal stages">
      {SIGNAL_STAGES.map((s, i) => (
        <li
          key={s}
          className={cx('step', i < current && 'is-done', i === current && (stage === 'closed' ? 'is-done' : 'is-current'))}
          aria-current={i === current ? 'step' : undefined}
        >
          {SIGNAL_STAGE_LABEL[s]}
        </li>
      ))}
    </ol>
  );
}
