// Editing the names of an ingredient that is already on the watchlist (EditIngredient.tsx). Pure: the saved
// terms become drafts for the term editor, and the edited drafts become the deletes, updates and inserts that
// bring the database to them. Administrators write ingredient_term directly (the ingredient_term_admin policy,
// 0001); every change is in audit_log, and a new or changed word is due for the check of the past (0034).
// The Japan codes are not names: they keep their own field on the row (JapanCodeEdit, set_japan_codes), so they
// are left out here and never touched by an edit.
import type { IngredientTerm, MatchMode, TermKind } from '../../lib/types';
import type { TermDraft } from './TermEditor';

/** The PMDA code Japan's label watch reads: a term of kind 'code' for Japan, not a name. */
export function isJapanCodeTerm(t: { kind: string; country_code: string | null }): boolean {
  return t.kind === 'code' && t.country_code === 'JP';
}

/** The ingredient's names as drafts, each keyed by its row id; the Japan code is left out. */
export function draftsOf(terms: IngredientTerm[]): TermDraft[] {
  return terms
    .filter((t) => !isJapanCodeTerm(t))
    .map((t) => ({
      uid: t.id,
      lang: t.lang,
      term: t.term,
      kind: t.kind,
      mode: t.mode,
      exclusions: t.exclusions.join(', '),
      country: t.country_code ?? '',
      source: t.source ?? 'manual',
    }));
}

export interface TermRow {
  lang: string;
  country_code: string | null;
  term: string;
  kind: TermKind;
  mode: MatchMode;
  exclusions: string[];
}

export interface TermPlan {
  remove: string[];
  update: { id: string; row: TermRow }[];
  insert: (TermRow & { source: string })[];
}

function rowOf(d: TermDraft): TermRow {
  return {
    lang: d.lang,
    country_code: d.country || null,
    term: d.term.trim(),
    kind: d.kind,
    mode: d.mode,
    exclusions: d.exclusions
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean),
  };
}

function same(a: TermRow, t: IngredientTerm): boolean {
  return (
    a.lang === t.lang &&
    a.country_code === (t.country_code ?? null) &&
    a.term === t.term &&
    a.kind === t.kind &&
    a.mode === t.mode &&
    a.exclusions.join('\u0000') === t.exclusions.join('\u0000')
  );
}

/**
 * What to write so the database holds the drafts. A saved name emptied in the editor is removed, a new empty one is
 * ignored. Throws when one word is written twice in one language (the table keeps a word once per language).
 */
export function planTermEdit(saved: IngredientTerm[], drafts: TermDraft[]): TermPlan {
  const byId = new Map(saved.filter((t) => !isJapanCodeTerm(t)).map((t) => [t.id, t]));
  const kept = drafts.filter((d) => d.term.trim());

  const seen = new Set<string>();
  for (const d of kept) {
    const k = `${d.lang}|${d.term.trim()}`;
    if (seen.has(k)) throw new Error(`“${d.term.trim()}” is written twice in the same language; keep it once.`);
    seen.add(k);
  }

  const keptIds = new Set(kept.map((d) => d.uid).filter((uid) => byId.has(uid)));
  const plan: TermPlan = { remove: [...byId.keys()].filter((id) => !keptIds.has(id)), update: [], insert: [] };
  for (const d of kept) {
    const row = rowOf(d);
    const was = byId.get(d.uid);
    if (!was) plan.insert.push({ ...row, source: d.source || 'manual' });
    else if (!same(row, was)) plan.update.push({ id: was.id, row });
  }
  return plan;
}

/** Nothing to write. */
export function isEmptyPlan(p: TermPlan): boolean {
  return p.remove.length === 0 && p.update.length === 0 && p.insert.length === 0;
}
