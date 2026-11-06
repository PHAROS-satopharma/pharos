import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDateTime } from '../../lib/format';
import { ROLE_LABEL } from '../../lib/labels';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import {
  MEANING,
  STATE_LABEL,
  type Meaning,
  type SignKind,
  type Signature,
  defaultMeaning,
  shortHash,
  signatureState,
} from './signoff';
import '../../styles/signoff.css';

function useSignatures(kind: SignKind, id: string) {
  return useQuery({
    queryKey: ['sign-off', kind, id],
    queryFn: async () => {
      const [rows, fp] = await Promise.all([
        supabase
          .from('sign_off')
          .select('id,record_sha256,meaning,signed_name,signed_role,comment,signed_at')
          .eq('record_kind', kind)
          .eq('record_id', id)
          .order('signed_at'),
        supabase.rpc('record_fingerprint', { p_kind: kind, p_id: id }),
      ]);
      return { signatures: unwrap<Signature[] | null>(rows) ?? [], fingerprint: unwrap<string | null>(fp) };
    },
  });
}

/**
 * The signatures on one record and, for a reviewer or an administrator, the signature form: what the signature
 * means, the password (checked by signing in again) and an optional comment. The database refuses a signature
 * without a password typed in the last five minutes, and never changes or removes one (0030, 0047).
 */
export function SignOff({ kind, id, name }: { kind: SignKind; id: string; name: string }) {
  const { session, role, canReview } = useAuth();
  const qc = useQueryClient();
  const sigs = useSignatures(kind, id);
  const [open, setOpen] = useState(false);
  const [meaning, setMeaning] = useState<Meaning>('reviewed');
  const [password, setPassword] = useState('');
  const [comment, setComment] = useState('');

  const sign = useMutation({
    mutationFn: async () => {
      const email = session?.user.email;
      if (!email) throw new Error('Your account has no e-mail address to sign with.');
      const auth = await supabase.auth.signInWithPassword({ email, password });
      if (auth.error) throw new Error('The password is not right.');
      return unwrap<string>(
        await supabase.rpc('sign_record', { p_kind: kind, p_id: id, p_meaning: meaning, p_comment: comment }),
      );
    },
    onSuccess: async () => {
      setOpen(false);
      setComment('');
      await qc.invalidateQueries({ queryKey: ['sign-off', kind, id] });
    },
    onSettled: () => setPassword(''),
  });

  function close() {
    setOpen(false);
    setPassword('');
    sign.reset();
  }

  const list = sigs.data?.signatures ?? [];
  return (
    <div className="signoff">
      <p className="signoff-title">Signatures</p>
      {sigs.isError ? (
        <Notice tone="error">The signatures could not be read: {errorMessage(sigs.error)}</Notice>
      ) : list.length === 0 ? (
        <p className="signoff-none">{sigs.isPending ? 'Reading the signatures…' : 'Not signed yet.'}</p>
      ) : (
        <ul className="signoff-list">
          {list.map((s) => {
            const state = signatureState(s.record_sha256, sigs.data?.fingerprint);
            return (
              <li key={s.id} className="signoff-item">
                <span className="signoff-who">
                  <strong>{s.signed_name}</strong>
                  <span className="signoff-role">{ROLE_LABEL[s.signed_role] ?? s.signed_role}</span>
                </span>
                <span className="signoff-what">
                  <span className="signoff-meaning">{MEANING[s.meaning]?.label ?? s.meaning}</span>
                  <span className="mono">{formatDateTime(s.signed_at)}</span>
                </span>
                <span className={cx('signoff-state', `signoff-state-${state}`)}>
                  {STATE_LABEL[state]}
                  <span className="mono" title={`SHA-256 of the report as it was signed: ${s.record_sha256}`}>
                    {shortHash(s.record_sha256)}
                  </span>
                </span>
                {s.comment ? (
                  <span className="signoff-comment" dir="auto">
                    {s.comment}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {canReview && !open ? (
        <div className="signoff-actions">
          <Button
            onClick={() => {
              setMeaning(defaultMeaning(role));
              setOpen(true);
            }}
            aria-label={`Sign the report ${name}`}
          >
            Sign this report
          </Button>
        </div>
      ) : null}
      {canReview && open ? (
        <form
          className="signoff-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (password) sign.mutate();
          }}
        >
          <p className="signoff-form-what">Sign {name}</p>
          <fieldset className="signoff-meanings">
            <legend className="field-label">What your signature means</legend>
            {(Object.keys(MEANING) as Meaning[]).map((m) => (
              <label key={m} className={cx('signoff-choice', meaning === m && 'is-selected')}>
                <input
                  type="radio"
                  name={`meaning-${kind}-${id}`}
                  value={m}
                  checked={meaning === m}
                  onChange={() => setMeaning(m)}
                />
                <span>{MEANING[m].statement}</span>
              </label>
            ))}
          </fieldset>
          <Field
            label="Your password"
            hint={
              <>
                Signing records your name, your role, the time and the SHA-256 of the report as it is now. It cannot
                be undone. No password yet? Set one under <Link to="/me">My account</Link>.
              </>
            }
          >
            <Input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <Field label="Comment (optional)">
            <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} dir="auto" />
          </Field>
          {sign.isError ? <Notice tone="error">Not signed: {errorMessage(sign.error)}</Notice> : null}
          <div className="signoff-form-actions">
            <Button type="submit" variant="primary" busy={sign.isPending} disabled={!password}>
              Sign electronically
            </Button>
            <Button onClick={close}>Cancel</Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
