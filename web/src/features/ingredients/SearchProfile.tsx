import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { MODE_LABEL, languageName } from '../../lib/labels';
import type { IngredientTerm } from '../../lib/types';
import { Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { AddGroup } from './AddGroup';
import { ClassLine } from './ClassLine';
import { linkOf, type ClassLink, type DrugClass } from './drugClasses';
import {
  PROFILE_MODE_HINT,
  PROFILE_MODE_LABEL,
  WORD_KIND_LABEL,
  profileMode,
  profileWords,
  switchesFor,
  type ProfileMode,
} from './searchProfile';

const MODES: ProfileMode[] = ['ingredient', 'ingredient_groups', 'custom'];

/**
 * The search profile of one ingredient: Ingredient only / Ingredient + groups / Custom (derived from the switches
 * of its classes), each class with its own switch, a group added by hand, and every word PHAROS looks for.
 */
export function SearchProfile({
  ingredient,
  terms,
  classes,
  classesFailed,
  isAdmin,
  languages,
}: {
  ingredient: { id: string; inn_en: string; atc_code: string | null };
  terms: IngredientTerm[];
  classes: DrugClass[];
  classesFailed: boolean;
  isAdmin: boolean;
  languages: string[];
}) {
  const qc = useQueryClient();
  const linked = classes
    .map((cls) => ({ cls, link: linkOf(ingredient.id, cls) }))
    .filter((x): x is { cls: DrugClass; link: ClassLink } => x.link !== undefined);
  const mode = profileMode(linked.map((x) => x.link));
  const setMode = useMutation({
    mutationFn: async (next: 'ingredient' | 'ingredient_groups') => {
      const changes = switchesFor(
        next,
        linked.map((x) => ({ class_id: x.cls.id, enabled: x.link.enabled })),
      );
      for (const c of changes) {
        unwrap(
          await supabase.rpc('set_class_search', { p_ingredient: ingredient.id, p_class: c.class_id, p_enabled: c.enabled }),
        );
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['drug-classes'] }),
  });
  const words = profileWords(terms, linked);
  const byLang = new Map<string, typeof words>();
  for (const w of words) byLang.set(w.lang, [...(byLang.get(w.lang) ?? []), w]);
  const langs = [...byLang.keys()].sort((a, b) => languageName(a).localeCompare(languageName(b)));
  const radioName = `profile-${ingredient.id}`;

  return (
    <section className="dc-section" aria-label={`Search profile of ${ingredient.inn_en}`}>
      <h3 className="dc-section-head">
        <span className="micro">Search profile</span>
        <span className="micro muted">{PROFILE_MODE_LABEL[mode]}</span>
      </h3>
      <fieldset className="dc-profile" disabled={!isAdmin || linked.length === 0 || setMode.isPending}>
        <legend className="visually-hidden">What is looked for</legend>
        {MODES.map((m) => (
          <label key={m} className={cx('dc-radio', m === 'custom' && mode !== 'custom' && 'is-off')} title={PROFILE_MODE_HINT[m]}>
            <input
              type="radio"
              name={radioName}
              value={m}
              checked={mode === m}
              disabled={m === 'custom'}
              onChange={() => {
                if (m !== 'custom') setMode.mutate(m);
              }}
            />
            <span>{PROFILE_MODE_LABEL[m]}</span>
          </label>
        ))}
      </fieldset>
      <p className="small muted dc-profile-hint">{PROFILE_MODE_HINT[mode]}</p>
      {setMode.isError ? <Notice tone="error">Not changed: {errorMessage(setMode.error)}</Notice> : null}

      {linked.length ? (
        linked.map(({ cls, link }) => (
          <ClassLine
            key={cls.id}
            cls={cls}
            link={link}
            ingredientId={ingredient.id}
            ingredientName={ingredient.inn_en}
            isAdmin={isAdmin}
            languages={languages}
          />
        ))
      ) : classesFailed ? (
        <p className="small danger">The drug classes could not be loaded.</p>
      ) : (
        <p className="small muted">
          {ingredient.atc_code
            ? 'Its group and the class above it are added from the ATC code in the next daily run.'
            : 'No ATC code, so no group from it. An administrator can add a group by hand.'}
        </p>
      )}
      {isAdmin ? <AddGroup ingredientId={ingredient.id} ingredientName={ingredient.inn_en} /> : null}

      <details className="dc-preview">
        <summary>
          <span className="micro">Words PHAROS looks for</span>
          <span className="micro muted">
            {words.length} in {langs.length} {langs.length === 1 ? 'language' : 'languages'}
          </span>
        </summary>
        <div className="dc-groups">
          {langs.map((l) => (
            <section key={l} className="dc-group" aria-label={languageName(l)}>
              <h4 className="dc-group-head">
                <span className="micro">{languageName(l)}</span>
                <span className="micro muted">{(byLang.get(l) ?? []).length}</span>
              </h4>
              <ul>
                {(byLang.get(l) ?? []).map((w) => (
                  <li key={`${w.kind}|${w.term}`} className="dc-word">
                    <span className="dc-word-text">
                      <span dir="auto" lang={l} className="term-word">
                        {w.term}
                      </span>{' '}
                      <span className="muted small">
                        {WORD_KIND_LABEL[w.kind]}
                        {w.from ? ` (${w.from})` : ''} · {MODE_LABEL[w.mode]}
                        {w.notInLiterature ? ' · notices only, not the literature' : ''}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </details>
    </section>
  );
}
