import { useState, type FormEvent } from 'react';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { PharosMark } from '../../ui/PharosMark';

type Mode = 'password' | 'link';

function friendly(message: string): string {
  const m = message.toLowerCase();
  if (m.includes('invalid login credentials')) {
    return 'That email and password do not match. Try again, or ask for a sign-in link instead.';
  }
  if (m.includes('signups not allowed') || m.includes('user not found')) {
    return 'This address has not been invited to PHAROS. Ask an administrator for an invitation.';
  }
  if (m.includes('email not confirmed')) {
    return 'This address has not accepted its invitation yet. Open the invitation email first.';
  }
  if (m.includes('rate limit') || m.includes('too many')) {
    return 'Too many attempts in a short time. Wait a minute and try again.';
  }
  return message;
}

export function SignIn() {
  const [mode, setMode] = useState<Mode>('password');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSentTo(null);
    const address = email.trim();
    if (!address) {
      setError('Enter your work email address.');
      return;
    }
    setBusy(true);
    try {
      if (mode === 'password') {
        const { error: err } = await supabase.auth.signInWithPassword({ email: address, password });
        if (err) setError(friendly(err.message));
      } else {
        const { error: err } = await supabase.auth.signInWithOtp({
          email: address,
          options: { shouldCreateUser: false, emailRedirectTo: window.location.origin },
        });
        if (err) setError(friendly(err.message));
        else setSentTo(address);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      <section className="signin-side" aria-label="PHAROS">
        <PharosMark variant="stacked" height={240} className="signin-mark" />
        <div className="signin-words">
          <h1 className="signin-title">Safety notifications from every regulator we watch.</h1>
          <ol className="signin-facts">
            <li className="signin-fact">
              <span className="signin-fact-index">01</span>
              <span>
                <strong>Read in its own language.</strong> Each regulator is screened as it publishes; nothing is
                translated.
              </span>
            </li>
            <li className="signin-fact">
              <span className="signin-fact-index">02</span>
              <span>
                <strong>Kept with the original.</strong> Every page and PDF is archived exactly as it was found.
              </span>
            </li>
            <li className="signin-fact">
              <span className="signin-fact-index">03</span>
              <span>
                <strong>Reviewed by name.</strong> Each notice is marked relevant or not by a named reviewer.
              </span>
            </li>
          </ol>
        </div>
        <span className="micro signin-by">by Sato Pharma</span>
      </section>

      <section className="signin-main">
        <form className="signin-form" onSubmit={(e) => void submit(e)} noValidate>
          <div className="signin-form-head">
            <span className="micro soft">PHAROS</span>
            <h2 className="signin-form-title">Sign in</h2>
          </div>
          <div className="tabs" role="tablist" aria-label="How to sign in">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'password'}
              className={cx('tab', mode === 'password' && 'is-active')}
              onClick={() => {
                setMode('password');
                setError(null);
                setSentTo(null);
              }}
            >
              Password
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'link'}
              className={cx('tab', mode === 'link' && 'is-active')}
              onClick={() => {
                setMode('link');
                setError(null);
              }}
            >
              Email me a link
            </button>
          </div>

          <Field label="Work email">
            <Input
              type="email"
              autoComplete="email"
              inputMode="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>

          {mode === 'password' ? (
            <Field label="Password">
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
          ) : (
            <p className="soft small">
              We send a one-time link to this address. Open it on this device and you are signed in.
            </p>
          )}

          {error ? <Notice tone="error">{error}</Notice> : null}
          {sentTo ? (
            <Notice tone="ok">
              A sign-in link is on its way to {sentTo}. It works once; if it does not arrive in a few minutes, check the
              spam folder.
            </Notice>
          ) : null}

          <Button type="submit" variant="primary" busy={busy} className="btn-block">
            {mode === 'password' ? 'Sign in' : 'Send the link'}
          </Button>

          <p className="soft small signin-foot">
            Access is by invitation only. If you need an account, ask a PHAROS administrator.
          </p>
        </form>
      </section>
    </div>
  );
}
