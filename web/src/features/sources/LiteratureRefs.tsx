// Literature references, Global and Local (Dr Sama, 8 Nov 2026; migration 0101): the first section of Sources.
// Each reference says how it was screened this week: searched by the app (with the number of searches), or checked
// by hand (who, when, what was found). Admins add, change and remove references (literature_ref's admin policy,
// every change in the audit log); reviewers and admins record a hand check (record_literature_check()).

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDateTime } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import {
  REF_NAME_MAX,
  REF_NOTE_MAX,
  SCOPE_EXPLAIN,
  SCOPE_TITLE,
  checkRef,
  nextRefSort,
  refRow,
  refStatus,
  weekDays,
  type LiteratureRef,
  type RefDraft,
  type RefScope,
  type RefWeek,
} from './literatureRefs';

const TONE_CLASS = { ok: 'is-read', warning: 'is-partial', danger: 'is-unread' } as const;
const SCOPES: RefScope[] = ['global', 'local'];

function useRefs() {
  return useQuery({
    queryKey: ['literature-refs'],
    queryFn: async () =>
      unwrap<LiteratureRef[]>(
        await supabase
          .from('literature_ref')
          .select('id, scope, name, url, searched_in, journal_like, note, sort, active')
          .eq('active', true)
          .order('sort'),
      ) ?? [],
  });
}

function useRefWeek(weekStart: Date) {
  const { from, to } = weekDays(weekStart);
  return useQuery({
    queryKey: ['literature-refs-week', from],
    queryFn: async () =>
      unwrap<RefWeek[] | null>(
        await supabase.rpc('literature_refs_week', { p_ingredient: null, p_from: from, p_to: to }),
      ) ?? [],
  });
}

function useRefresh() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['literature-refs'] }),
      qc.invalidateQueries({ queryKey: ['literature-refs-week'] }),
      qc.invalidateQueries({ queryKey: ['ingredient-literature-refs'] }),
    ]);
}

export function LiteratureRefs({ weekStart }: { weekStart: Date }) {
  const { isAdmin, canReview } = useAuth();
  const refs = useRefs();
  const week = useRefWeek(weekStart);
  const [adding, setAdding] = useState<RefScope | null>(null);
  const failed = refs.error ?? week.error;
  const byId = new Map((week.data ?? []).map((w) => [w.id, w]));

  return (
    <section className="hz-card lit-refs" aria-labelledby="lit-refs-title">
      <header className="hz-head">
        <h2 className="hz-country" id="lit-refs-title">
          Literature references
        </h2>
        <p className="hz-regs">
          Where the literature is screened for every ingredient, and the negative result of each, week by week.
        </p>
      </header>
      {failed ? (
        <ErrorNote
          title="The literature references could not be loaded."
          error={failed}
          onRetry={() => {
            void refs.refetch();
            void week.refetch();
          }}
        />
      ) : refs.isPending || week.isPending ? (
        <Loading label="Reading the literature references" />
      ) : (
        <div className="lit-scopes">
          {SCOPES.map((scope) => {
            const list = (refs.data ?? []).filter((r) => r.scope === scope);
            return (
              <div className="hz-block" key={scope}>
                <h3 className="hz-block-title">{SCOPE_TITLE[scope]}</h3>
                <p className="hz-note lit-explain">{SCOPE_EXPLAIN[scope]}</p>
                {list.length > 0 ? (
                  <ul className="hz-pages">
                    {list.map((r) => (
                      <RefLine
                        key={r.id}
                        refRow={r}
                        week={byId.get(r.id)}
                        all={refs.data ?? []}
                        isAdmin={isAdmin}
                        canReview={canReview}
                      />
                    ))}
                  </ul>
                ) : (
                  <p className="hz-note">None yet.</p>
                )}
                {isAdmin ? (
                  adding === scope ? (
                    <RefForm scope={scope} refs={refs.data ?? []} onDone={() => setAdding(null)} />
                  ) : (
                    <div className="hz-edit-actions">
                      <Button size="sm" onClick={() => setAdding(scope)}>
                        Add a {scope} reference
                      </Button>
                    </div>
                  )
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function RefLine({
  refRow: r,
  week,
  all,
  isAdmin,
  canReview,
}: {
  refRow: LiteratureRef;
  week: RefWeek | undefined;
  all: LiteratureRef[];
  isAdmin: boolean;
  canReview: boolean;
}) {
  const [editing, setEditing] = useState<'change' | 'remove' | 'nothing' | 'found' | null>(null);
  const status = week ? refStatus(week, formatDateTime) : null;
  const href = r.url ? safeHref(r.url) : null;
  const byHand = r.searched_in.length === 0;
  return (
    <li className={cx('hz-page', status ? TONE_CLASS[status.tone] : 'is-unread')}>
      {href ? (
        <a className="hz-page-link" href={href} target="_blank" rel="noopener noreferrer">
          {r.name}
        </a>
      ) : (
        <span className="hz-page-link">{r.name}</span>
      )}
      <span className="hz-page-kind">{byHand ? 'By hand' : 'By the app'}</span>
      <span className="hz-read">{status ? status.text : 'Not screened this week'}</span>
      {r.note ? <span className="hz-note">{r.note}</span> : null}
      {!editing && (isAdmin || (byHand && canReview)) ? (
        <span className="hz-page-tools">
          {byHand && canReview ? (
            <>
              <Button size="sm" onClick={() => setEditing('nothing')}>
                Checked: nothing found
              </Button>
              <Button size="sm" variant="quiet" onClick={() => setEditing('found')}>
                Checked: found something
              </Button>
            </>
          ) : null}
          {isAdmin ? (
            <>
              <Button size="sm" variant="quiet" onClick={() => setEditing('change')}>
                Change
              </Button>
              <Button size="sm" variant="quiet" onClick={() => setEditing('remove')}>
                Remove
              </Button>
            </>
          ) : null}
        </span>
      ) : null}
      {editing === 'nothing' ? <CheckedNothing refRow={r} onDone={() => setEditing(null)} /> : null}
      {editing === 'found' ? <CheckedFound refRow={r} onDone={() => setEditing(null)} /> : null}
      {editing === 'change' ? (
        <RefForm scope={r.scope} refs={all} refRow={r} onDone={() => setEditing(null)} />
      ) : null}
      {editing === 'remove' ? <RemoveRef refRow={r} onDone={() => setEditing(null)} /> : null}
    </li>
  );
}

/** "Nothing found", asked twice: a recorded check is kept for the inspection and never changed. */
function CheckedNothing({ refRow: r, onDone }: { refRow: LiteratureRef; onDone: () => void }) {
  const refresh = useRefresh();
  const save = useMutation({
    mutationFn: async () =>
      unwrap<string>(await supabase.rpc('record_literature_check', { p_ref: r.id, p_result: 'nothing' })),
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  return (
    <div className="hz-edit" role="group" aria-label={`Record a check of ${r.name}`}>
      <p>
        Record that you searched <strong>{r.name}</strong> for every ingredient on the watchlist today and found
        nothing? The check is kept for the inspection and cannot be changed.
      </p>
      {save.isError ? <Notice tone="error">Not recorded: {errorMessage(save.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button variant="primary" busy={save.isPending} onClick={() => save.mutate()}>
          Record: nothing found
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function CheckedFound({ refRow: r, onDone }: { refRow: LiteratureRef; onDone: () => void }) {
  const refresh = useRefresh();
  const [note, setNote] = useState('');
  const [tried, setTried] = useState(false);
  const problem = !note.trim() ? 'Say what was found: the article, its link or its reference.' : null;
  const save = useMutation({
    mutationFn: async () =>
      unwrap<string>(
        await supabase.rpc('record_literature_check', { p_ref: r.id, p_result: 'found', p_note: note.trim() }),
      ),
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  return (
    <form
      className="hz-edit"
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (!problem) save.mutate();
      }}
    >
      <Field label={`What was found in ${r.name}`}>
        <Textarea value={note} maxLength={REF_NOTE_MAX} rows={2} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {tried && problem ? <Notice tone="error">{problem}</Notice> : null}
      {save.isError ? <Notice tone="error">Not recorded: {errorMessage(save.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button type="submit" variant="primary" busy={save.isPending}>
          Record the check
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Add a reference to a list, or change one (`refRow`). A reference she adds is checked by hand. */
function RefForm({
  scope,
  refs,
  refRow: existing,
  onDone,
}: {
  scope: RefScope;
  refs: LiteratureRef[];
  refRow?: LiteratureRef;
  onDone: () => void;
}) {
  const refresh = useRefresh();
  const [draft, setDraft] = useState<RefDraft>(() =>
    existing
      ? { scope, name: existing.name, url: existing.url ?? '', note: existing.note ?? '' }
      : { scope, name: '', url: '', note: '' },
  );
  const [tried, setTried] = useState(false);
  const problem = checkRef(draft, refs, existing?.id);
  const save = useMutation({
    mutationFn: async () => {
      const row = refRow(draft);
      if (existing) {
        unwrapChanged(
          await supabase.from('literature_ref').update(row).eq('id', existing.id).select('id'),
          'this reference',
        );
      } else {
        unwrap<null>(await supabase.from('literature_ref').insert({ ...row, sort: nextRefSort(refs, scope) }));
      }
    },
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  return (
    <form
      className="hz-edit"
      onSubmit={(e) => {
        e.preventDefault();
        setTried(true);
        if (!problem) save.mutate();
      }}
    >
      <div className="form-grid">
        <Field label="Name in the list">
          <Input
            value={draft.name}
            maxLength={REF_NAME_MAX}
            placeholder={scope === 'local' ? 'Al-Azhar Medical Journal' : 'Cochrane Library'}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </Field>
        <Field label="Link">
          <Input
            type="url"
            value={draft.url}
            placeholder="https://"
            onChange={(e) => setDraft({ ...draft, url: e.target.value })}
          />
        </Field>
        <Field label="Note (optional)" className="form-grid-full">
          <Textarea
            value={draft.note}
            maxLength={REF_NOTE_MAX}
            rows={2}
            onChange={(e) => setDraft({ ...draft, note: e.target.value })}
          />
        </Field>
      </div>
      {!existing ? (
        <Notice>
          A reference you add is checked by hand: each week, record “Checked: nothing found” or what you found.
        </Notice>
      ) : null}
      {tried && problem ? <Notice tone="error">{problem}</Notice> : null}
      {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button type="submit" variant="primary" busy={save.isPending}>
          {existing ? 'Save the change' : `Add to ${SCOPE_TITLE[scope]}`}
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Remove a reference, in two steps. It is switched off, never deleted: its checks and the audit log stay. */
function RemoveRef({ refRow: r, onDone }: { refRow: LiteratureRef; onDone: () => void }) {
  const refresh = useRefresh();
  const remove = useMutation({
    mutationFn: async () => {
      unwrapChanged(
        await supabase.from('literature_ref').update({ active: false }).eq('id', r.id).select('id'),
        'this reference',
      );
    },
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  return (
    <div className="hz-edit hz-remove" role="group" aria-label={`Remove ${r.name}`}>
      <p>
        Remove <strong>{r.name}</strong> from the {SCOPE_TITLE[r.scope]} list? The checks already recorded for it
        stay in the reports of the weeks they were made.
      </p>
      {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
          Remove the reference
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Keep it
        </Button>
      </div>
    </div>
  );
}
