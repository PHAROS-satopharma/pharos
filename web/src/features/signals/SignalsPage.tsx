import { useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useSignals, type SignalView } from './queries';
import { DueNote, PriorityTag, StagePill } from './SignalUi';
import { formatCairoDate, formatNumber } from '../../lib/format';
import { SIGNAL_OUTCOME_LABEL } from '../../lib/labels';
import { Stat, StatRow } from '../../ui/Stat';
import { Empty, ErrorNote, Loading } from '../../ui/States';
import { PageHead } from '../../ui/Text';
import { cx } from '../../ui/cx';

const VIEWS: { key: SignalView; label: string }[] = [
  { key: 'open', label: 'Open' },
  { key: 'closed', label: 'Closed' },
  { key: 'all', label: 'All' },
];

function readView(p: URLSearchParams): SignalView {
  const v = p.get('view');
  return v === 'closed' || v === 'all' ? v : 'open';
}

export function SignalsPage() {
  const [params, setParams] = useSearchParams();
  const view = readView(params);
  const signals = useSignals(view);
  const open = useSignals('open');
  const navigate = useNavigate();
  const rows = signals.data ?? [];

  const counts = useMemo(() => {
    const o = open.data ?? [];
    return {
      open: o.length,
      overdue: o.filter((s) => s.overdue).length,
      validation: o.filter((s) => s.stage === 'validation').length,
      assessment: o.filter((s) => s.stage === 'assessment').length,
      action: o.filter((s) => s.stage === 'action').length,
    };
  }, [open.data]);

  return (
    <div className="page">
      <PageHead
        eyebrow="Signal management"
        title="Signals"
        lede="A notice marked Relevant opens a signal. Each one is validated, assessed and closed with its outcome, step by step, and every step is kept as it was recorded."
        foot={
          <StatRow label="Open signals">
            <Stat value={open.isPending ? null : counts.open} label="Open" />
            <Stat value={open.isPending ? null : counts.overdue} label="Overdue" tone={counts.overdue > 0 ? 'relevant' : undefined} />
            <Stat value={open.isPending ? null : counts.validation} label="In validation" />
            <Stat value={open.isPending ? null : counts.assessment} label="In assessment" />
            <Stat value={open.isPending ? null : counts.action} label="Action open" />
          </StatRow>
        }
      />

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Which signals">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              className={cx('segment', view === v.key && 'is-active')}
              aria-pressed={view === v.key}
              onClick={() => setParams(v.key === 'open' ? {} : { view: v.key }, { replace: true })}
            >
              {v.label}
            </button>
          ))}
        </div>
        <span className="toolbar-count">
          {signals.isPending ? ' ' : `${formatNumber(rows.length)} ${rows.length === 1 ? 'signal' : 'signals'}`}
        </span>
      </div>

      {signals.isPending ? (
        <Loading label="Reading the signals" />
      ) : signals.isError ? (
        <ErrorNote title="The signals could not be loaded." error={signals.error} onRetry={() => void signals.refetch()} />
      ) : rows.length === 0 ? (
        <Empty title={view === 'closed' ? 'No signal has been closed yet.' : 'No open signal.'}>
          <p>
            Open a notice marked Relevant and choose <strong>Open a signal</strong> in its side column. The signal then
            appears here with its due date.
          </p>
        </Empty>
      ) : (
        <div className="issues-wrap">
          <table className="table issues signals">
            <thead>
              <tr>
                <th scope="col">Signal</th>
                <th scope="col">Ingredient</th>
                <th scope="col">Stage</th>
                <th scope="col">Priority</th>
                <th scope="col">Owner</th>
                <th scope="col">{view === 'closed' ? 'Outcome' : 'Due'}</th>
                <th scope="col" className="num">
                  Notices
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr
                  key={s.id}
                  className={cx('issue-row', s.overdue && 'is-overdue')}
                  onClick={() => navigate(`/signals/${s.id}`)}
                >
                  <td data-label="Signal" className="col-title">
                    <Link to={`/signals/${s.id}`} className="title-link" dir="auto" onClick={(e) => e.stopPropagation()}>
                      {s.title}
                    </Link>
                    <span className="title-meta">
                      <span className="mono">{s.ref}</span>
                      <span>Opened {formatCairoDate(s.opened_at)}</span>
                    </span>
                  </td>
                  <td data-label="Ingredient">{s.ingredient ?? <span className="soft">—</span>}</td>
                  <td data-label="Stage">
                    <StagePill stage={s.stage} />
                  </td>
                  <td data-label="Priority">
                    <PriorityTag priority={s.priority} />
                  </td>
                  <td data-label="Owner">{s.owner ?? <span className="soft">Nobody yet</span>}</td>
                  <td data-label={view === 'closed' ? 'Outcome' : 'Due'} className="nowrap">
                    {s.stage === 'closed' ? (
                      <span className="small">{s.outcome ? SIGNAL_OUTCOME_LABEL[s.outcome].label : 'Closed'}</span>
                    ) : (
                      <DueNote signal={s} />
                    )}
                  </td>
                  <td data-label="Notices" className="num">
                    {formatNumber(s.notices)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
