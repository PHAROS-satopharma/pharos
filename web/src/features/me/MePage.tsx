import { useEffect, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { passwordChosen, supabase, telegramBotUsername } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate } from '../../lib/format';
import { ROLE_LABEL } from '../../lib/labels';
import type { SubscriptionRow } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import { ThemeSwitch } from '../../ui/ThemeSwitch';
import { SubscriptionEditor } from '../people/Subscriptions';
import { RealMessages } from './RealMessages';

function TelegramLink() {
  const { person, refreshPerson } = useAuth();
  const [code, setCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const linkedAt = person?.telegram_linked_at ?? null;
  const [linkedBefore] = useState(linkedAt);

  // While a code is showing, look every few seconds for the bot to have linked the chat.
  useEffect(() => {
    if (!code) return;
    const t = window.setInterval(refreshPerson, 5000);
    const stop = window.setTimeout(() => window.clearInterval(t), 5 * 60_000);
    return () => {
      window.clearInterval(t);
      window.clearTimeout(stop);
    };
  }, [code, refreshPerson]);

  const justLinked = code !== null && linkedAt !== null && linkedAt !== linkedBefore;

  async function makeCode() {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const c = unwrap<string | null>(await supabase.rpc('create_link_token'));
      if (!c) throw new Error('No code came back.');
      setCode(String(c));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const deepLink = code && telegramBotUsername ? `https://t.me/${telegramBotUsername}?start=${encodeURIComponent(code)}` : null;

  async function copy() {
    if (!deepLink) return;
    try {
      await navigator.clipboard.writeText(deepLink);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="telegram">
      {justLinked ? (
        <Notice tone="ok">Telegram is connected. Messages now go to that chat.</Notice>
      ) : linkedAt ? (
        <p className="telegram-status">
          <Tag tone="success">Connected</Tag>
          <span>
            Since <span className="mono">{formatCairoDate(linkedAt)}</span>. Messages go to that chat.
          </span>
        </p>
      ) : (
        <p className="telegram-status">
          <Tag tone="warning">Not connected</Tag>
          <span>Until you connect, PHAROS cannot send you anything.</span>
        </p>
      )}

      {code && !justLinked ? (
        <div className="link-box">
          {deepLink ? (
            <>
              <span className="field-label">Your link</span>
              <a href={deepLink} target="_blank" rel="noopener noreferrer" className="deep-link mono">
                {deepLink}
              </a>
              <div className="link-box-actions">
                <Button size="sm" onClick={() => void copy()}>
                  {copied ? 'Copied' : 'Copy the link'}
                </Button>
              </div>
              <p className="small">
                Open the link on the phone or computer where you use Telegram, then press <strong>Start</strong> in the
                chat with the bot. The link works once and expires in 24 hours.
              </p>
            </>
          ) : (
            <p className="small">
              Open the PHAROS bot in Telegram and send <span className="mono">/start {code}</span>. The code works once
              and expires in 24 hours.
            </p>
          )}
        </div>
      ) : null}

      {error ? <Notice tone="error">No code was made: {error}</Notice> : null}
      <Button variant={linkedAt ? 'secondary' : 'primary'} busy={busy} onClick={() => void makeCode()}>
        {linkedAt ? 'Connect a different chat' : 'Connect Telegram'}
      </Button>
    </div>
  );
}

export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const [pw, setPw] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (pw.length < 10) {
      setMsg({ tone: 'error', text: 'Use at least 10 characters.' });
      return;
    }
    if (pw !== again) {
      setMsg({ tone: 'error', text: 'The two passwords are not the same.' });
      return;
    }
    setBusy(true);
    const { error } = await supabase.auth.updateUser({ password: pw });
    setBusy(false);
    if (error) setMsg({ tone: 'error', text: error.message });
    else {
      setPw('');
      setAgain('');
      setMsg({ tone: 'ok', text: 'Your password is set. You can sign in with it from now on.' });
      passwordChosen();
      onDone?.();
    }
  }

  return (
    <form className="form-grid" onSubmit={(e) => void submit(e)}>
      <Field label="New password">
        <Input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
      </Field>
      <Field label="The same again">
        <Input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
      </Field>
      <div className="form-grid-action">
        <Button type="submit" busy={busy} disabled={!pw || !again}>
          Set the password
        </Button>
      </div>
      {msg ? (
        <div className="form-grid-full">
          <Notice tone={msg.tone}>{msg.text}</Notice>
        </div>
      ) : null}
    </form>
  );
}

export function MePage() {
  const { person, isAdmin, signOut } = useAuth();
  const personId = person?.id ?? '';
  const subs = useQuery({
    queryKey: ['my-subs', personId],
    enabled: personId !== '',
    queryFn: async () =>
      unwrap<SubscriptionRow[] | null>(
        await supabase
          .from('subscription')
          .select('id,person_id,kind,ingredient_id,ingredient:ingredient_id(inn_en)')
          .eq('person_id', personId)
          .order('created_at'),
      ) ?? [],
  });

  if (!person) return <Loading />;

  return (
    <div className="page narrow">
      <PageHead eyebrow="My account" title={person.full_name} lede={`${person.email ?? ''} · ${ROLE_LABEL[person.role]}`} />

      <section className="section">
        <SectionHead index="01" title="Telegram" />
        <TelegramLink />
      </section>

      <section className="section">
        <SectionHead index="02" title="What I receive" />
        <p className="small muted">
          Ingredient notices arrive as soon as they are found. Class-wide notices come together in one digest each
          morning, Cairo time. Messages carry the regulator’s public notice only, never review comments.
        </p>
        {subs.isPending ? (
          <Loading />
        ) : subs.isError ? (
          <ErrorNote error={subs.error} onRetry={() => void subs.refetch()} />
        ) : (
          <SubscriptionEditor
            personId={person.id}
            subs={subs.data}
            allowHealth={isAdmin}
            invalidate={[['my-subs'], ['people']]}
          />
        )}
      </section>

      {isAdmin ? (
        <section className="section">
          <SectionHead index="03" title="Real Telegram messages" />
          <RealMessages />
        </section>
      ) : null}

      <section className="section">
        <SectionHead index={isAdmin ? '04' : '03'} title="Password" />
        <p className="small muted">Set or change the password you sign in with. The email link keeps working too.</p>
        <PasswordForm />
      </section>

      <section className="section">
        <SectionHead index={isAdmin ? '05' : '04'} title="This device" />
        <div className="device-row">
          <div className="device-item">
            <span className="field-label">Light or dark</span>
            <ThemeSwitch className="theme-switch-page" />
          </div>
          <div className="device-item">
            <span className="field-label">Session</span>
            <Button onClick={() => void signOut()}>Sign out</Button>
          </div>
        </div>
      </section>
    </div>
  );
}
