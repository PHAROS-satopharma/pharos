import { Link, useParams } from 'react-router-dom';
import { useSignal, useSignalEvents, useSignalNotices } from './queries';
import { DueNote, PriorityTag, StagePill, StageSteps } from './SignalUi';
import { StepForm } from './StepForm';
import { useAuth } from '../../lib/auth';
import { formatCairoDate, formatDate, formatDateTime } from '../../lib/format';
import { DOC_TYPE_LABEL, SIGNAL_OUTCOME_LABEL, SIGNAL_PRIORITY_LABEL, SIGNAL_STEP_LABEL } from '../../lib/labels';
import type { SignalEventRow } from '../../lib/types';
import { Country } from '../../ui/Flag';
import { Empty, ErrorNote, Loading } from '../../ui/States';
import { StatusPill } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';

/** What a step changed, in words, under its name in the history. */
function stepDetail(e: SignalEventRow): string | null {
  switch (e.step) {
    case 'opened':
      return e.due ? `Validation due ${formatDate(e.due)}` : null;
    case 'validated':
      return [e.priority ? `${SIGNAL_PRIORITY_LABEL[e.priority]} priority` : null, e.due ? `assessment due ${formatDate(e.due)}` : null]
        .filter(Boolean)
        .join(', ');
    case 'prioritised':
      return e.priority ? `Now ${SIGNAL_PRIORITY_LABEL[e.priority].toLowerCase()} priority${e.due ? `, assessment due ${formatDate(e.due)}` : ''}` : null;
    case 'assigned':
      return e.owner ? `Owner: ${e.owner.full_name}` : null;
    case 'assessed':
      return e.outcome ? `${SIGNAL_OUTCOME_LABEL[e.outcome].label}${e.due ? `, action due ${formatDate(e.due)}` : ''}` : null;
    case 'reopened':
      return e.due ? `Assessment due ${formatDate(e.due)}` : null;
    default:
      return null;
  }
}

export function SignalPage() {
  const { id = '' } = useParams();
  const signal = useSignal(id);
  const notices = useSignalNotices(id);
  const events = useSignalEvents(id);
  const { canReview } = useAuth();

  if (signal.isPending) return <Loading label="Opening the signal" />;
  if (signal.isError) {
    return <ErrorNote title="This signal could not be loaded." error={signal.error} onRetry={() => void signal.refetch()} />;
  }
  const s = signal.data;
  if (!s) {
    return (
      <Empty title="This signal does not exist." action={<Link to="/signals">Back to the signals</Link>}>
        <p>The link may be incomplete.</p>
      </Empty>
    );
  }

  return (
    <div className="page detail">
      <header className="detail-head masthead">
        <Link to="/signals" className="back-link">
          <span aria-hidden>←</span> All signals
        </Link>
        <div className="detail-eyebrow">
          <span className="eyebrow">
            <span className="eyebrow-rule" aria-hidden />
            Signal <span className="mono">{s.ref}</span>
          </span>
          <span className="soft small">Opened {formatCairoDate(s.opened_at)}</span>
        </div>
        <h1 className="detail-title" dir="auto">
          {s.title}
        </h1>
        <dl className="detail-facts">
          <div className="detail-fact">
            <dt>Stage</dt>
            <dd>
              <StagePill stage={s.stage} />
            </dd>
          </div>
          <div className="detail-fact">
            <dt>Priority</dt>
            <dd>
              <PriorityTag priority={s.priority} />
            </dd>
          </div>
          <div className="detail-fact">
            <dt>Ingredient</dt>
            <dd>{s.ingredient ?? '—'}</dd>
          </div>
          <div className="detail-fact">
            <dt>Owner</dt>
            <dd>{s.owner ?? 'Nobody yet'}</dd>
          </div>
          <div className="detail-fact">
            <dt>{s.stage === 'closed' ? 'Outcome' : 'Due'}</dt>
            <dd>
              {s.stage === 'closed' ? (s.outcome ? SIGNAL_OUTCOME_LABEL[s.outcome].label : 'Closed') : <DueNote signal={s} />}
              {s.stage !== 'closed' && s.next_due ? <span className="detail-fact-sub">{formatDate(s.next_due)}</span> : null}
            </dd>
          </div>
        </dl>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="section detail-section">
            <SectionHead index="01" title="The notices behind this signal" />
            {notices.isPending ? (
              <Loading label="Reading the notices" />
            ) : notices.isError ? (
              <ErrorNote error={notices.error} onRetry={() => void notices.refetch()} />
            ) : notices.data.length === 0 ? (
              <p className="soft">No notice is linked.</p>
            ) : (
              <ul className="signal-notices">
                {notices.data.map((n) => (
                  <li key={n.id} className="signal-notice">
                    <Link to={`/issue/${n.id}`} className="title-link" dir="auto" lang={n.lang ?? undefined}>
                      {n.title}
                    </Link>
                    <span className="title-meta">
                      <Country name={n.anchor_country} />
                      <span>{n.anchor_regulator ?? '—'}</span>
                      <span>{DOC_TYPE_LABEL[n.doc_type]}</span>
                      <span>{formatDate(n.first_date)}</span>
                      <StatusPill status={n.status} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="section detail-section">
            <SectionHead index="02" title="Signal history" aside={<span className="soft small">Every step as it was recorded</span>} />
            {events.isPending ? (
              <Loading label="Reading the history" />
            ) : events.isError ? (
              <ErrorNote error={events.error} onRetry={() => void events.refetch()} />
            ) : (
              <ol className="timeline">
                {events.data.map((e) => {
                  const detail = stepDetail(e);
                  return (
                    <li key={e.id} className="timeline-item">
                      <div className="timeline-line">
                        <strong>{e.person?.full_name ?? 'Someone'}</strong> · {SIGNAL_STEP_LABEL[e.step]}
                      </div>
                      {detail ? <div className="small">{detail}</div> : null}
                      <div className="soft small">{formatDateTime(e.created_at)}</div>
                      {e.comment ? (
                        <p className="timeline-comment" dir="auto">
                          {e.comment}
                        </p>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>

        <aside className="detail-aside">
          <section className="panel decision" aria-labelledby="signal-step-title">
            <div className="panel-head">
              <h2 id="signal-step-title" className="panel-title">
                Signal steps
              </h2>
              <StagePill stage={s.stage} />
            </div>
            <StageSteps stage={s.stage} />
            {canReview ? (
              <StepForm signal={s} />
            ) : (
              <p className="soft small">You can read every step. Recording one needs a reviewer or administrator account.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
