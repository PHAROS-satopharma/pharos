import { formatDateTime } from '../../lib/format';
import { NOTIF_KIND_LABEL, STATUS_LABEL } from '../../lib/labels';
import type { NotificationRow, ReviewEventRow } from '../../lib/types';
import { Monogram } from '../../ui/Monogram';
import { StatusPill, Tag } from '../../ui/Tag';

export function ReviewHistory({ events }: { events: ReviewEventRow[] }) {
  if (events.length === 0) return <p className="soft small">No decision has been recorded yet.</p>;
  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id} className="timeline-item">
          <div className="timeline-line">
            <strong>{e.person?.full_name ?? 'Someone'}</strong>
            <span className="visually-hidden">
              {' '}
              changed {STATUS_LABEL[e.from_status]} to {STATUS_LABEL[e.to_status]}
            </span>
          </div>
          <div className="timeline-change" aria-hidden="true">
            <StatusPill status={e.from_status} />
            <span className="timeline-arrow">→</span>
            <StatusPill status={e.to_status} />
          </div>
          <div className="soft small">{formatDateTime(e.created_at)}</div>
          {e.comment ? (
            <p className="timeline-comment" dir="auto">
              {e.comment}
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** `mine`: the reader is not an admin and sees only the messages sent to them. */
export function WhoWasNotified({ rows, mine = false }: { rows: NotificationRow[]; mine?: boolean }) {
  if (rows.length === 0)
    return (
      <p className="soft small">
        {mine
          ? 'You have not been sent a message about this notification.'
          : 'Nobody has been sent a message about this notification.'}
      </p>
    );
  return (
    <ul className="notified">
      {rows.map((n) => (
        <li key={n.id} className="notified-item">
          <div className="notified-line">
            <span className="notified-person">
              <Monogram name={n.person?.full_name ?? '?'} />
              {n.person?.full_name ?? 'A person no longer listed'}
            </span>
            {n.dry_run ? (
              <Tag tone="quiet" title="Test mode: the message was prepared but not sent.">
                Not sent (test mode)
              </Tag>
            ) : n.error ? (
              <Tag tone="danger" title={n.error}>
                Failed
              </Tag>
            ) : (
              <Tag tone="success">Sent</Tag>
            )}
          </div>
          <div className="soft small notified-meta">
            {NOTIF_KIND_LABEL[n.kind]} · {formatDateTime(n.sent_at)}
          </div>
        </li>
      ))}
    </ul>
  );
}
