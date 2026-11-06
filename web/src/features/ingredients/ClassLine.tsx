import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { formatCairoDate } from '../../lib/format';
import { MODE_LABEL, languageName } from '../../lib/labels';
import { Button } from '../../ui/Button';
import { Input, Toggle } from '../../ui/Input';
import { Select } from '../../ui/Select';
import { Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { cx } from '../../ui/cx';
import {
  ORIGIN_LABEL,
  RELATION_LABEL,
  className,
  isDue,
  wordsByLanguage,
  wordsSummary,
  type ClassLink,
  type ClassTerm,
  type DrugClass,
} from './drugClasses';
import '../../styles/drug-classes.css';

type HitState = { busy: boolean; count?: number; error?: string };

/**
 * One drug class of an ingredient: "Fluoroquinolones (J01MA) · 17 words in 12 languages · from the ATC code ·
 * its group", its switch (Searched / Not searched) and Confirm. Opening it lists the class words by language; each
 * can be tested against the archive, and an administrator adds or removes words. A class word is looked for only
 * in notices in its own language, and a notice that names only the class reaches the daily digest, never an
 * immediate message. The class above the group starts switched off: its words are read first. A group added by
 * hand can be removed from the ingredient; a class from the ATC code is switched off instead. A searched class can
 * be kept out of the literature search (0051): its words then stay in notices only, so a wide class such as
 * NSAID does not flood PubMed and PubMed Central.
 */
export function ClassLine({
  cls,
  link,
  ingredientId,
  ingredientName,
  isAdmin,
  languages,
}: {
  cls: DrugClass;
  link: ClassLink;
  ingredientId: string;
  ingredientName: string;
  isAdmin: boolean;
  languages: string[];
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [hits, setHits] = useState<Record<string, HitState>>({});
  const [lang, setLang] = useState('');
  const [word, setWord] = useState('');
  const [removing, setRemoving] = useState<string | null>(null);
  const [unlinking, setUnlinking] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['drug-classes'] });

  // The database records who confirmed and when, from the signed-in administrator and its own clock.
  const confirm = useMutation({
    mutationFn: async () => {
      unwrap(await supabase.rpc('confirm_drug_class', { p_class: cls.id }));
    },
    onSuccess: refresh,
  });
  // On or off: switching on makes the words due for the check of the past and the literature look-back.
  const setSearch = useMutation({
    mutationFn: async (enabled: boolean) => {
      unwrap(await supabase.rpc('set_class_search', { p_ingredient: ingredientId, p_class: cls.id, p_enabled: enabled }));
    },
    onSuccess: refresh,
  });
  // In the literature or notices only: the words stay in notices either way. Papers already found are kept.
  const setLiterature = useMutation({
    mutationFn: async (on: boolean) => {
      unwrap(await supabase.rpc('set_class_literature', { p_ingredient: ingredientId, p_class: cls.id, p_on: on }));
    },
    onSuccess: refresh,
  });
  const inLiterature = link.literature !== false;
  const unlink = useMutation({
    mutationFn: async () => {
      unwrap(await supabase.rpc('unlink_search_group', { p_ingredient: ingredientId, p_class: cls.id }));
    },
    onSuccess: async () => {
      setUnlinking(false);
      await refresh();
    },
  });
  const add = useMutation({
    mutationFn: async () => {
      unwrap(await supabase.rpc('add_class_term', { p_class: cls.id, p_lang: lang, p_term: word.trim() }));
    },
    onSuccess: async () => {
      setWord('');
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(await supabase.rpc('remove_class_term', { p_term: id }));
    },
    onSuccess: async () => {
      setRemoving(null);
      await refresh();
    },
  });

  async function test(t: ClassTerm) {
    setHits((h) => ({ ...h, [t.id]: { busy: true } }));
    const { data, error } = await supabase.rpc('archive_hit_count', { p_term: t.term, p_lang: t.lang });
    setHits((h) => ({
      ...h,
      [t.id]: error ? { busy: false, error: errorMessage(error.message) } : { busy: false, count: Number(data ?? 0) },
    }));
  }

  const groups = wordsByLanguage(cls.class_term);
  const due = link.enabled && cls.class_term.some(isDue);
  const langOptions = [...new Set([...languages, ...cls.class_term.map((t) => t.lang)])]
    .sort((a, b) => languageName(a).localeCompare(languageName(b)))
    .map((l) => ({ value: l, label: languageName(l) }));
  const panelId = `dc-words-${cls.id}`;

  return (
    <div className={cx('dc', open && 'is-open', !link.enabled && 'is-off')}>
      <div className="dc-line">
        <button
          type="button"
          className="dc-toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(!open)}
        >
          <span className="dc-mark" aria-hidden="true" />
          <span className="dc-name">{className(cls)}</span>
        </button>
        <span className="dc-meta">
          {wordsSummary(cls.class_term)} · {ORIGIN_LABEL[cls.origin]} · {RELATION_LABEL[link.relation]}
        </span>
        <span className="dc-switch">
          {isAdmin ? (
            <Toggle
              checked={link.enabled}
              disabled={setSearch.isPending}
              onChange={(v) => setSearch.mutate(v)}
              label={link.enabled ? 'Searched' : 'Not searched'}
            />
          ) : (
            <Tag tone="quiet">{link.enabled ? 'Searched' : 'Not searched'}</Tag>
          )}
        </span>
        {link.enabled ? (
          <span className="dc-switch">
            {isAdmin ? (
              <Toggle
                checked={inLiterature}
                disabled={setLiterature.isPending}
                onChange={(v) => setLiterature.mutate(v)}
                label={inLiterature ? 'In the literature search' : 'Notices only'}
              />
            ) : !inLiterature ? (
              <Tag tone="quiet">Notices only</Tag>
            ) : null}
          </span>
        ) : null}
        <span className="dc-confirm">
          {cls.confirmed_at ? (
            <span className="small">
              Confirmed by {cls.confirmed_by_name ?? 'an administrator'}, {formatCairoDate(cls.confirmed_at)}
            </span>
          ) : isAdmin ? (
            <Button
              size="sm"
              busy={confirm.isPending}
              onClick={() => confirm.mutate()}
              aria-label={`Confirm the class ${cls.name_en}`}
              title="Records that you have checked this class and its words."
            >
              Confirm
            </Button>
          ) : (
            <Tag tone="quiet">Not confirmed</Tag>
          )}
        </span>
      </div>
      {!link.enabled ? (
        <p className="dc-note small muted">
          {link.relation === 'parent'
            ? 'The class above its group. Its words are not looked for until an administrator has read them and ' +
              'switched it on: a wide class brings noise, and each English word is a 12-month look-back on PubMed ' +
              'and PubMed Central.'
            : 'Not searched: its words are not looked for in notices or in the literature.'}
        </p>
      ) : due ? (
        <p className="dc-note small muted">
          New words: the stored notices of the last 12 months are being checked with them (three runs a day).
        </p>
      ) : null}
      {link.enabled && !inLiterature ? (
        <p className="dc-note small muted">
          Notices only: its words are looked for in notices but not on PubMed or PubMed Central. Papers already
          found by them stay.
        </p>
      ) : null}
      {confirm.isError ? <Notice tone="error">Not confirmed: {errorMessage(confirm.error)}</Notice> : null}
      {setSearch.isError ? <Notice tone="error">Not changed: {errorMessage(setSearch.error)}</Notice> : null}
      {setLiterature.isError ? <Notice tone="error">Not changed: {errorMessage(setLiterature.error)}</Notice> : null}

      {open ? (
        <div className="dc-words" id={panelId}>
          <p className="small muted">
            Each word is looked for only in notices written in its own language. A notice that names the class but
            not the ingredient goes to the daily digest.
          </p>
          {groups.length === 0 ? (
            <p className="small">No words yet.{isAdmin ? ' Add the words notices use for this class.' : ''}</p>
          ) : (
            <div className="dc-groups">
              {groups.map(([l, list]) => (
                <section key={l} className="dc-group" aria-label={languageName(l)}>
                  <h4 className="dc-group-head">
                    <span className="micro">{languageName(l)}</span>
                    <span className="micro muted">{list.length}</span>
                  </h4>
                  <ul>
                    {list.map((t) => {
                      const h = hits[t.id];
                      return (
                        <li key={t.id} className="dc-word">
                          <span className="dc-word-text">
                            <span dir="auto" lang={l} className="term-word">
                              {t.term}
                            </span>{' '}
                            <span className="muted small">
                              {MODE_LABEL[t.mode]}
                              {t.source === 'manual' ? ' · added by hand' : ''}
                            </span>
                          </span>
                          <span className="dc-word-actions">
                            <Button size="sm" variant="quiet" busy={h?.busy} onClick={() => void test(t)}>
                              Test against archive
                            </Button>
                            {isAdmin && removing === t.id ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="danger"
                                  busy={remove.isPending}
                                  onClick={() => remove.mutate(t.id)}
                                >
                                  Remove “{t.term}”
                                </Button>
                                <Button size="sm" variant="quiet" onClick={() => setRemoving(null)}>
                                  Keep
                                </Button>
                              </>
                            ) : isAdmin ? (
                              <Button
                                size="sm"
                                variant="quiet"
                                onClick={() => setRemoving(t.id)}
                                aria-label={`Remove ${t.term}`}
                              >
                                Remove
                              </Button>
                            ) : null}
                            {h && !h.busy ? (
                              <span className={h.error ? 'small danger' : 'small'} role="status">
                                {h.error
                                  ? `Test failed: ${h.error}`
                                  : h.count === 0
                                    ? 'No archived notice contains it'
                                    : `${h.count} archived ${h.count === 1 ? 'notice contains' : 'notices contain'} it`}
                              </span>
                            ) : null}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
          {remove.isError ? <Notice tone="error">Not removed: {errorMessage(remove.error)}</Notice> : null}

          {isAdmin ? (
            <form
              className="dc-add"
              onSubmit={(e) => {
                e.preventDefault();
                if (lang && word.trim().length >= 2) add.mutate();
              }}
            >
              <Select
                aria-label="Language of the new word"
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                placeholder="Language…"
                options={langOptions}
              />
              <Input
                aria-label="New class word, as notices write it"
                placeholder="e.g. Fluorchinolon"
                value={word}
                dir="auto"
                lang={lang || undefined}
                onChange={(e) => setWord(e.target.value)}
              />
              <Button type="submit" size="sm" busy={add.isPending} disabled={!lang || word.trim().length < 2}>
                Add word
              </Button>
            </form>
          ) : null}
          {add.isError ? <Notice tone="error">Not added: {errorMessage(add.error)}</Notice> : null}

          {isAdmin && link.relation === 'manual' ? (
            <div className="dc-remove">
              {unlinking ? (
                <>
                  <Button size="sm" variant="danger" busy={unlink.isPending} onClick={() => unlink.mutate()}>
                    Remove {cls.name_en} from {ingredientName}
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => setUnlinking(false)}>
                    Keep
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="quiet"
                  onClick={() => setUnlinking(true)}
                  title="The group and its words stay; they are no longer looked for with this ingredient."
                >
                  Remove this group from {ingredientName}
                </Button>
              )}
            </div>
          ) : null}
          {unlink.isError ? <Notice tone="error">Not removed: {errorMessage(unlink.error)}</Notice> : null}
        </div>
      ) : null}
    </div>
  );
}
