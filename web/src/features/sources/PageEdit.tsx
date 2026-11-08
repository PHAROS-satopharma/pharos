// Dr Sama edits her own pages (her feedback, 8 Nov 2026). Admins only: the screen shows these to admins, and
// regulator_page's and regulator's admin policies (0032, 0004) refuse anyone else. Every change is in the audit
// log (audit_regulator_page, 0032; audit_regulator, 0098).

import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap, unwrapChanged } from '../../lib/api';
import { Button } from '../../ui/Button';
import { Field, Input, Textarea } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';
import type { CardRegulator, PageKind, RegulatorPage } from './horizontal';
import {
  PAGE_KINDS,
  authorityId,
  authorityRow,
  checkAuthority,
  checkPage,
  nextSort,
  pageRow,
  readerWarning,
  type AuthorityDraft,
  type PageDraft,
} from './pageRules';

function useRefreshPages() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ['regulator-pages'] }),
      qc.invalidateQueries({ queryKey: ['regulators'] }),
      qc.invalidateQueries({ queryKey: ['ingredient-screen'] }),
    ]);
}

/** The fields of one link: name, address, what it is, a note. */
function LinkFields({
  draft,
  set,
  regulators,
}: {
  draft: PageDraft;
  set: (d: PageDraft) => void;
  /** Shown as a choice only when the country has more than one authority. */
  regulators?: CardRegulator[];
}) {
  return (
    <div className="form-grid">
      {regulators && regulators.length > 1 ? (
        <Field label="Authority">
          <Select
            value={draft.regulator_id}
            onChange={(e) => set({ ...draft, regulator_id: e.target.value })}
            options={regulators.map((r) => ({ value: r.id, label: r.name }))}
          />
        </Field>
      ) : null}
      <Field label="Name in the list">
        <Input
          value={draft.label}
          maxLength={200}
          placeholder="Safety communications"
          onChange={(e) => set({ ...draft, label: e.target.value })}
        />
      </Field>
      <Field label="Link">
        <Input
          type="url"
          value={draft.url}
          placeholder="https://"
          onChange={(e) => set({ ...draft, url: e.target.value })}
        />
      </Field>
      <Field label="What it is">
        <Select
          value={draft.kind}
          onChange={(e) => set({ ...draft, kind: e.target.value as PageKind })}
          options={PAGE_KINDS}
        />
      </Field>
      <Field label="Note (optional)" className="form-grid-full">
        <Textarea
          value={draft.note}
          maxLength={1000}
          rows={2}
          onChange={(e) => set({ ...draft, note: e.target.value })}
        />
      </Field>
    </div>
  );
}

/** Add a link to a country's card, or change one (`page`). */
export function PageForm({
  regulators,
  pages,
  page,
  onDone,
}: {
  regulators: CardRegulator[];
  pages: RegulatorPage[];
  page?: RegulatorPage;
  onDone: () => void;
}) {
  const refresh = useRefreshPages();
  const [draft, setDraft] = useState<PageDraft>(() =>
    page
      ? { regulator_id: page.regulator_id, kind: page.kind, label: page.label, url: page.url, note: page.note ?? '' }
      : { regulator_id: regulators[0]?.id ?? '', kind: 'safety', label: '', url: '', note: '' },
  );
  const [tried, setTried] = useState(false);
  const problem = checkPage(draft, pages, page?.id);
  const warning = page ? readerWarning(page, draft.url) : null;

  const save = useMutation({
    mutationFn: async () => {
      const row = pageRow(draft);
      if (page) {
        unwrapChanged(await supabase.from('regulator_page').update(row).eq('id', page.id).select('id'), 'this link');
      } else {
        unwrap<null>(
          await supabase.from('regulator_page').insert({ ...row, sort: nextSort(pages, row.regulator_id) }),
        );
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
      <LinkFields draft={draft} set={setDraft} regulators={page ? undefined : regulators} />
      {warning ? <Notice>{warning}</Notice> : null}
      {tried && problem ? <Notice tone="error">{problem}</Notice> : null}
      {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button type="submit" variant="primary" busy={save.isPending}>
          {page ? 'Save the change' : 'Add the link'}
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Remove a link, in two steps. The audit log keeps what it was. */
export function RemovePage({ page, onDone }: { page: RegulatorPage; onDone: () => void }) {
  const refresh = useRefreshPages();
  const remove = useMutation({
    mutationFn: async () => {
      unwrapChanged(await supabase.from('regulator_page').delete().eq('id', page.id).select('id'), 'this link');
    },
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  return (
    <div className="hz-edit hz-remove" role="group" aria-label={`Remove ${page.label}`}>
      <p>
        Remove <strong>{page.label}</strong> from your list?
        {page.read_by.length > 0
          ? ' The app keeps reading it through its own reader; only the link in your list goes.'
          : ''}
      </p>
      {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}
      <div className="hz-edit-actions">
        <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
          Remove the link
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Keep it
        </Button>
      </div>
    </div>
  );
}

const NEW_AUTHORITY = '__new__';

/**
 * A local reference: an authority PHAROS lists without pages of yours (Saudi Arabia, the UAE, Egypt …), or a
 * new one, with its first link. Once it has a link its country joins your list, the ingredient screen and the
 * weekly report.
 */
export function AddAuthority({
  regulators,
  pages,
  onDone,
}: {
  regulators: CardRegulator[];
  pages: RegulatorPage[];
  onDone: () => void;
}) {
  const refresh = useRefreshPages();
  const withPages = useMemo(() => new Set(pages.map((p) => p.regulator_id)), [pages]);
  const choices = useMemo(
    () =>
      regulators
        .filter((r) => !withPages.has(r.id))
        .sort((a, b) => a.country_name.localeCompare(b.country_name) || a.name.localeCompare(b.name)),
    [regulators, withPages],
  );
  const takenIds = useMemo(() => new Set(regulators.map((r) => r.id)), [regulators]);
  const [choice, setChoice] = useState('');
  const [authority, setAuthority] = useState<AuthorityDraft>({ country_name: '', country_code: '', name: '', short: '' });
  const [link, setLink] = useState<PageDraft>({ regulator_id: '', kind: 'safety', label: '', url: '', note: '' });
  const [tried, setTried] = useState(false);
  const isNew = choice === NEW_AUTHORITY;
  const regulatorId = isNew ? authorityId(authority.short || authority.name) : choice;
  const problem = !choice
    ? 'Choose the authority, or “A new authority”.'
    : (isNew ? checkAuthority(authority, takenIds) : null) ?? checkPage({ ...link, regulator_id: regulatorId }, pages);

  const save = useMutation({
    mutationFn: async () => {
      if (isNew) {
        unwrap<null>(await supabase.from('regulator').insert(authorityRow(authority)));
        // Saved: if the link below fails, the next try picks this authority from the list.
        await refresh();
        setChoice(regulatorId);
      }
      unwrap<null>(
        await supabase
          .from('regulator_page')
          .insert({ ...pageRow({ ...link, regulator_id: regulatorId }), sort: nextSort(pages, regulatorId) }),
      );
    },
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });

  return (
    <section className="panel add-panel" aria-labelledby="add-authority-title">
      <div className="panel-head">
        <h2 id="add-authority-title" className="panel-title">
          Add a local reference
        </h2>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <p className="small muted">
        An authority you check by hand, with its first link. Its country then joins your list; add more links on its
        card. The app does not read a link you add: it says “open it yourself”, so a week with nothing found there
        is recorded as checked by you.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setTried(true);
          if (!problem) save.mutate();
        }}
      >
        <div className="form-grid">
          <Field label="Authority">
            <Select
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              placeholder="Choose the authority"
              options={[
                ...choices.map((r) => ({ value: r.id, label: `${r.country_name} — ${r.name}` })),
                { value: NEW_AUTHORITY, label: 'A new authority…' },
              ]}
            />
          </Field>
        </div>
        {isNew ? (
          <div className="form-grid">
            <Field label="Country">
              <Input
                value={authority.country_name}
                placeholder="Egypt"
                onChange={(e) => setAuthority({ ...authority, country_name: e.target.value })}
              />
            </Field>
            <Field label="Country code" hint="Two letters, as on its flag">
              <Input
                value={authority.country_code}
                maxLength={2}
                placeholder="EG"
                onChange={(e) => setAuthority({ ...authority, country_code: e.target.value })}
              />
            </Field>
            <Field label="Authority’s name">
              <Input
                value={authority.name}
                placeholder="Egyptian Drug Authority"
                onChange={(e) => setAuthority({ ...authority, name: e.target.value })}
              />
            </Field>
            <Field label="Short name" hint="Latin letters, such as EDA">
              <Input
                value={authority.short}
                maxLength={24}
                onChange={(e) => setAuthority({ ...authority, short: e.target.value })}
              />
            </Field>
          </div>
        ) : null}
        <h3 className="hz-block-title">Its first link</h3>
        <LinkFields draft={link} set={setLink} />
        {tried && problem ? <Notice tone="error">{problem}</Notice> : null}
        {save.isError ? <Notice tone="error">Not saved: {errorMessage(save.error)}</Notice> : null}
        <div className="hz-edit-actions">
          <Button type="submit" variant="primary" busy={save.isPending}>
            Add the local reference
          </Button>
        </div>
      </form>
    </section>
  );
}
