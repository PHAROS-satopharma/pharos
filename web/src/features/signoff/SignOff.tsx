import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDateTime } from '../../lib/format';
import { ROLE_LABEL } from '../../lib/labels';
import { supabase } from '../../lib/supabase';
import type { PersonRole } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';

export type SignKind = 'monthly_report' | 'signal';
type Meaning = 'reviewed' | 'approved';

interface Signature {
  id: string;
  record_sha256: string;
  meaning: Meaning;
  signed_name: string;
  signed_role: PersonRole;
  comment: string | null;
  signed_at: string;
}

const MEANING: Record<Meaning, { label: string; statement: string }> = {
  reviewed: { label: 'Reviewed', statement: 'I have reviewed this record.' },
  approved: { label: 'Approved', statement: 'I approve this record.' },
};

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
 * The signatures on one record and, for whoever may sign it, the signature form: the meaning, the password
 * (checked by signing in again) and an optional comment. The database refuses a signature without a password
 * typed in the last five minutes, and never changes or removes one.
 */
export function SignOff({ kind, id, canSign, compact = false }: { kind: SignKind; id: string; canSign: boolean; compact?: boolean }) {
  const { session } = useAuth();
  const qc = useQueryClient();
  const sigs = useSignatures(kind, id);
  const [open, setOpen] = useState(false);
  const [meaning, setMeaning] = useState<Meaning>(kind === 'monthly_report' ? 'approved' : 'reviewed');
  const [password, setPassword] = useState('');
  const [comment, setComment] = useState('');

  const sign = useMutation({
    mutationFn: async () => {
      const email = session?.user.email;
      if (!email) throw new Error('Your account has no e-mail address to sign with.');
      const auth = await supabase.auth.signInWithPassword({ email, password });
      if (auth.error) throw new Error('The password is not right.');
      return unwrap<string>(await supabase.rpc('sign_record', { p_kind: kind, p_id: id, p_meaning: meaning, p_comment: comment }));
    },
    onSuccess: async () => {
      setOpen(false);
      setPassword('');
      setComment('');
      await qc.invalidateQueries({ queryKey: ['sign-off', kind, id] });
    },
    onSettled: () => setPassword(''),
  });

  const list = sigs.data?.signatures ?? [];
  return (
    <div className={compact ? 'sign-off sign-off-compact' : 'sign-off'}>
      {list.length === 0 ? (
        <p className="soft small">{sigs.isPending ? 'Reading the signatures…' : 'Not signed yet.'}</p>
      ) : (
        <ul className="sign-off-list">
          {list.map((s) => {
            const changed = sigs.data?.fingerprint != null && s.record_sha256 !== sigs.data.fingerprint;
            return (
              <li key={s.id}>
                <Tag tone={changed ? 'warning' : 'success'}>{MEANING[s.meaning].label}</Tag>{' '}
                <strong>{s.signed_name}</strong> <span className="soft">({ROLE_LABEL[s.signed_role]})</span>,{' '}
                <span className="mono small">{formatDateTime(s.signed_at)}</span>
                {changed ? <span className="cell-sub">The record changed after this signature.</span> : null}
                {s.comment ? (
                  <span className="cell-sub" dir="auto">
                    {s.comment}
                  </span>
                ) : null}
                <span className="cell-sub mono" title="SHA-256 of the record as it was signed">
                  {s.record_sha256.slice(0, 16)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {sigs.isError ? <Notice tone="error">The signatures could not be read: {errorMessage(sigs.error)}</Notice> : null}

      {canSign && !open ? (
        <Button size="sm" onClick={() => setOpen(true)}>
          Sign
        </Button>
      ) : null}
      {canSign && open ? (
        <form
          className="sign-off-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (password) sign.mutate();
          }}
        >
          <fieldset className="sign-off-meaning">
            <legend className="field-label">What your signature means</legend>
            {(Object.keys(MEANING) as Meaning[]).map((m) => (
              <label key={m} className="radio">
                <input type="radio" name={`meaning-${id}`} value={m} checked={meaning === m} onChange={() => setMeaning(m)} />{' '}
                {MEANING[m].statement}
              </label>
            ))}
          </fieldset>
          <Field label="Your password" hint="Signing records your name, role, the time and a fingerprint of the record. It cannot be undone.">
            <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Field label="Comment (optional)">
            <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} dir="auto" />
          </Field>
          {sign.isError ? <Notice tone="error">Not signed: {errorMessage(sign.error)}</Notice> : null}
          <div className="button-row">
            <Button type="submit" variant="primary" size="sm" busy={sign.isPending} disabled={!password}>
              Sign electronically
            </Button>
            <Button
              size="sm"
              onClick={() => {
                setOpen(false);
                setPassword('');
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
