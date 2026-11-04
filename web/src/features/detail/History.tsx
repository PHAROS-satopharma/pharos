import { formatDateTime } from '../../lib/format';
import { NOTIF_KIND_LABEL, STATUS_LABEL } from '../../lib/labels';
import type { NotificationRow, ReviewEventRow } from '../../lib/types';
import { Tag } from '../../ui/Tag';

export function ReviewHistory({ events }: { events: ReviewEventRow[] }) {
  if (events.length === 0) return <p className="soft small">No decision has been recorded yet.</p>;
  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id} className="timeline-item">
          <div className="timeline-line">
            <strong>{e.person?.full_name ?? 'Someone'}</strong> changed {STATUS_LABEL[e.from_status]} to{' '}
            <strong>{STATUS_LABEL[e.to_status]}</strong>
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

export function WhoWasNotified({ rows }: { rows: NotificationRow[] }) {
  if (rows.length === 0) return <p className="soft small">Nobody has been sent a message about this notification.</p>;
  return (
    <ul className="notified">
      {rows.map((n) => (
        <li key={n.id} className="notified-item">
          <div className="notified-line">
            <span>{n.person?.full_name ?? 'A person no longer listed'}</span>
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
          <div className="soft small">
            {NOTIF_KIND_LABEL[n.kind]} · {formatDateTime(n.sent_at)}
          </div>
        </li>
      ))}
    </ul>
  );
}
