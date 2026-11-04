import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatCairoDate } from '../../lib/format';
import { ROLE_LABEL } from '../../lib/labels';
import { ROLES, type Person, type PersonRole, type SubscriptionRow } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { PageHead } from '../../ui/Text';
import { SubscriptionEditor } from './Subscriptions';

interface PersonWithSubs extends Person {
  subscription: SubscriptionRow[];
}

function InvitePanel({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<PersonRole>('reader');
  const [sent, setSent] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: () => invoke<{ person_id: string }>('invite-person', { email: email.trim(), full_name: name.trim(), role }),
    onSuccess: async () => {
      setSent(email.trim());
      setEmail('');
      setName('');
      await qc.invalidateQueries({ queryKey: ['people'] });
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (email.trim() && name.trim()) invite.mutate();
  }

  return (
    <section className="panel add-panel" aria-labelledby="invite-title">
      <div className="panel-head">
        <h2 id="invite-title" className="panel-title">
          Invite a person
        </h2>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Close
        </Button>
      </div>
      <form className="form-grid" onSubmit={submit}>
        <Field label="Full name">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" required />
        </Field>
        <Field label="Work email">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" required />
        </Field>
        <Field label="Role">
          <Select
            value={role}
            onChange={(e) => setRole(e.target.value as PersonRole)}
            options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))}
          />
        </Field>
        <div className="form-grid-action">
          <Button type="submit" variant="primary" busy={invite.isPending} disabled={!email.trim() || !name.trim()}>
            Send the invitation
          </Button>
        </div>
      </form>
      <p className="small muted">
        Readers see everything. Reviewers also record decisions and confirm or split copies. Administrators also manage
        the watchlist, the sources and people.
      </p>
      {invite.isError ? <Notice tone="error">Not invited: {errorMessage(invite.error)}</Notice> : null}
      {sent ? <Notice tone="ok">An invitation is on its way to {sent}.</Notice> : null}
    </section>
  );
}

export function PeoplePage() {
  const { person: me } = useAuth();
  const qc = useQueryClient();
  const [inviting, setInviting] = useState(false);

  const people = useQuery({
    queryKey: ['people'],
    queryFn: async () =>
      unwrap<PersonWithSubs[] | null>(
        await supabase
          .from('person')
          .select(
            'id,auth_user_id,full_name,email,role,telegram_chat_id,telegram_linked_at,active,created_at,' +
              'subscription(id,person_id,kind,ingredient_id,ingredient:ingredient_id(inn_en))',
          )
          .order('full_name'),
      ) ?? [],
  });

  const update = useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<Pick<Person, 'role' | 'active'>> }) => {
      unwrap<null>(await supabase.from('person').update(patch).eq('id', id));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['people'] }),
  });

  return (
    <div className="page">
      <PageHead
        eyebrow="Administration"
        title="People"
        lede="Who can sign in, what they may do, and which Telegram messages they receive."
        actions={
          !inviting ? (
            <Button variant="primary" onClick={() => setInviting(true)}>
              Invite a person
            </Button>
          ) : null
        }
      />
      {inviting ? <InvitePanel onDone={() => setInviting(false)} /> : null}
      {update.isError ? <Notice tone="error">Not changed: {errorMessage(update.error)}</Notice> : null}

      {people.isPending ? (
        <Loading label="Reading the people" />
      ) : people.isError ? (
        <ErrorNote error={people.error} onRetry={() => void people.refetch()} />
      ) : people.data.length === 0 ? (
        <Empty title="Nobody has been invited yet." />
      ) : (
        <Table className="people">
          <thead>
            <tr>
              <th scope="col">Person</th>
              <th scope="col">Role</th>
              <th scope="col">Can sign in</th>
              <th scope="col">Telegram</th>
              <th scope="col">Messages</th>
            </tr>
          </thead>
          <tbody>
            {people.data.map((p) => {
              const self = p.id === me?.id;
              return (
                <tr key={p.id} className={p.active ? undefined : 'is-off'}>
                  <td>
                    <div className="strong">{p.full_name}</div>
                    <div className="small muted">{p.email ?? 'No email'}</div>
                    {!p.auth_user_id ? <div className="small muted">Invitation not accepted yet</div> : null}
                  </td>
                  <td>
                    <Select
                      aria-label={`Role of ${p.full_name}`}
                      value={p.role}
                      disabled={self || update.isPending}
                      title={self ? 'You cannot change your own role.' : undefined}
                      onChange={(e) => update.mutate({ id: p.id, patch: { role: e.target.value as PersonRole } })}
                      options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))}
                    />
                  </td>
                  <td>
                    <Toggle
                      checked={p.active}
                      disabled={self || update.isPending}
                      onChange={(v) => update.mutate({ id: p.id, patch: { active: v } })}
                      label={p.active ? 'Yes' : 'Switched off'}
                    />
                  </td>
                  <td className="small">
                    {p.telegram_linked_at ? (
                      <>
                        Linked <span className="mono">{formatCairoDate(p.telegram_linked_at)}</span>
                      </>
                    ) : (
                      <span className="muted">Not linked</span>
                    )}
                  </td>
                  <td className="col-subs">
                    <SubscriptionEditor
                      personId={p.id}
                      subs={p.subscription ?? []}
                      allowHealth
                      invalidate={[['people'], ['my-subs']]}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </div>
  );
}
