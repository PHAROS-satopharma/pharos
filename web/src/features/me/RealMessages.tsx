import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDateTime } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Toggle } from '../../ui/Input';
import { ErrorNote, Loading, Notice } from '../../ui/States';

interface TestSend {
  ok: boolean;
  request_id?: number;
  reason?: string;
}

interface TestResult {
  done: boolean;
  ok?: boolean;
  status?: number;
  reason?: string | null;
}

/** telegram_test_delivered(): did Telegram accept YOUR latest test message? */
interface TestDelivery {
  state: 'none' | 'pending' | 'delivered' | 'failed';
  at?: string;
  reason?: string | null;
}

interface WouldHaveGone {
  id: string;
  kind: string;
  sent_at: string;
  summary: string | null;
}

/** Admin only: send yourself a test, read what would have gone, then turn real messages on yourself. */
export function RealMessages() {
  const { person } = useAuth();
  const qc = useQueryClient();
  const linked = Boolean(person?.telegram_linked_at);

  const state = useQuery({
    queryKey: ['telegram-sending'],
    queryFn: async () => {
      const setting = unwrap<{ value: unknown } | null>(
        await supabase.from('app_setting').select('value').eq('key', 'telegram_dry_run').maybeSingle(),
      );
      // Only this admin's own latest test, and only once Telegram answered 200 with ok=true, unlocks step 3.
      const delivery = unwrap<TestDelivery>(await supabase.rpc('telegram_test_delivered'));
      const queued = unwrap<WouldHaveGone[] | null>(
        await supabase
          .from('notification')
          .select('id,kind,sent_at,summary')
          .eq('dry_run', true)
          .order('sent_at', { ascending: false })
          .limit(3),
      ) ?? [];
      return { dryRun: setting?.value !== false, delivery, queued };
    },
    // While Telegram has not answered yet, look again every few seconds.
    refetchInterval: (query) => (query.state.data?.delivery.state === 'pending' ? 3000 : false),
  });

  const [sending, setSending] = useState(false);
  const [requestId, setRequestId] = useState<number | null>(null);
  const [result, setResult] = useState<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(null);
  const [approved, setApproved] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);

  // pg_net hands the message to Telegram a moment later: read Telegram's answer until it arrives.
  useEffect(() => {
    if (requestId === null) return;
    let tries = 0;
    const t = window.setInterval(async () => {
      tries += 1;
      try {
        const r = unwrap<TestResult>(await supabase.rpc('telegram_test_result', { p_request_id: requestId }));
        if (!r.done && tries < 20) return;
        window.clearInterval(t);
        setRequestId(null);
        if (!r.done) setResult({ tone: 'error', text: 'Telegram has not answered yet. Look in the PHAROS chat.' });
        else if (r.ok) setResult({ tone: 'ok', text: 'Telegram delivered it. Look in the PHAROS chat.' });
        else setResult({ tone: 'error', text: `Telegram refused it: ${r.reason ?? `status ${r.status}`}` });
        void qc.invalidateQueries({ queryKey: ['telegram-sending'] });
      } catch (e) {
        window.clearInterval(t);
        setRequestId(null);
        setResult({ tone: 'error', text: errorMessage(e) });
      }
    }, 1500);
    return () => window.clearInterval(t);
  }, [requestId, qc]);

  async function sendTest() {
    setSending(true);
    setResult(null);
    try {
      const r = unwrap<TestSend>(await supabase.rpc('send_telegram_test'));
      if (r.ok && r.request_id != null) {
        setResult({ tone: 'info', text: 'Sending…' });
        setRequestId(r.request_id);
      } else {
        setResult({ tone: 'error', text: r.reason ?? 'It was not sent.' });
      }
    } catch (e) {
      setResult({ tone: 'error', text: errorMessage(e) });
    } finally {
      setSending(false);
      // Step 3 follows this new test: pending, then delivered or failed.
      setApproved(false);
      void qc.invalidateQueries({ queryKey: ['telegram-sending'] });
    }
  }

  async function setDryRun(next: boolean) {
    setSwitching(true);
    setSwitchError(null);
    try {
      unwrapChanged(
        await supabase.from('app_setting').update({ value: next }).eq('key', 'telegram_dry_run').select('key'),
        'the sending switch',
      );
      setApproved(false);
      await qc.invalidateQueries({ queryKey: ['telegram-sending'] });
    } catch (e) {
      setSwitchError(errorMessage(e));
    } finally {
      setSwitching(false);
    }
  }

  if (state.isPending) return <Loading />;
  if (state.isError) return <ErrorNote error={state.error} onRetry={() => void state.refetch()} />;
  const { dryRun, delivery, queued } = state.data;
  const lastTestAt = delivery.at ?? null;
  const delivered = delivery.state === 'delivered';

  return (
    <div className="telegram">
      {dryRun ? (
        <p>
          <strong>Dry run.</strong> PHAROS writes down every message it would send, and sends none of them.
        </p>
      ) : (
        <Notice tone="ok">Real messages are on. Notices go to every linked person who receives them.</Notice>
      )}

      <div className="link-box">
        <span className="field-label">1 · Test message to you</span>
        <p className="small">
          One real message goes to your own Telegram chat, and to nobody else.
          {lastTestAt ? (
            <>
              {' '}Your last test: <span className="mono">{formatDateTime(lastTestAt)}</span>
              {delivered ? ', delivered by Telegram.' : delivery.state === 'pending' ? ', waiting for Telegram’s answer…' : ', not delivered.'}
            </>
          ) : null}
        </p>
        <div className="link-box-actions">
          <Button size="sm" busy={sending || requestId !== null} disabled={!linked} onClick={() => void sendTest()}>
            Send me a test message
          </Button>
        </div>
        {!linked ? <p className="small muted">Connect your Telegram above first.</p> : null}
        {result ? <Notice tone={result.tone}>{result.text}</Notice> : null}
      </div>

      <div className="link-box">
        <span className="field-label">2 · What would have gone</span>
        {queued.length === 0 ? (
          <p className="small muted">Nothing yet. The first notice found after the history load will appear here.</p>
        ) : (
          queued.map((n) => (
            <div key={n.id}>
              <span className="small muted mono">{formatDateTime(n.sent_at)}</span>
              <div className="excerpt">{n.summary ?? '—'}</div>
            </div>
          ))
        )}
      </div>

      {dryRun ? (
        <div className="link-box">
          <span className="field-label">3 · Turn real messages on</span>
          <Toggle
            checked={approved && delivered}
            disabled={!delivered}
            onChange={setApproved}
            label="I received the test message and approve sending real messages."
          />
          {delivery.state === 'none' ? <p className="small muted">Send yourself a test message first.</p> : null}
          {delivery.state === 'pending' ? <p className="small muted">Waiting for Telegram’s answer…</p> : null}
          {delivery.state === 'failed' ? (
            <Notice tone="error">
              Your last test message was not delivered: {delivery.reason ?? 'no reason was given.'} Send a new one.
            </Notice>
          ) : null}
          <div className="link-box-actions">
            <Button variant="primary" size="sm" busy={switching} disabled={!approved || !delivered} onClick={() => void setDryRun(false)}>
              Turn real messages on
            </Button>
          </div>
          {switchError ? <Notice tone="error">Not changed: {switchError}</Notice> : null}
        </div>
      ) : (
        <div className="link-box-actions">
          <Button size="sm" busy={switching} onClick={() => void setDryRun(true)}>
            Back to dry run
          </Button>
          {switchError ? <Notice tone="error">Not changed: {switchError}</Notice> : null}
        </div>
      )}
    </div>
  );
}
