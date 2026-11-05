import { Fragment, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { personNames } from '../../lib/people';
import { useAuth } from '../../lib/auth';
import { useCountryIndex } from '../../lib/regulators';
import { formatCairoDate } from '../../lib/format';
import { MODE_LABEL, TERM_KIND_LABEL, languageName } from '../../lib/labels';
import type { Ingredient, IngredientTerm } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Toggle } from '../../ui/Input';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { Tag } from '../../ui/Tag';
import { PageHead } from '../../ui/Text';
import { AddIngredient } from './AddIngredient';

interface IngredientWithTerms extends Ingredient {
  confirmed_by_person: { full_name: string } | null;
  ingredient_term: IngredientTerm[];
}

function TermsList({ terms }: { terms: IngredientTerm[] }) {
  const byLang = new Map<string, IngredientTerm[]>();
  for (const t of terms) byLang.set(t.lang, [...(byLang.get(t.lang) ?? []), t]);
  const idx = useCountryIndex();
  const langs = [...byLang.keys()].sort((a, b) => languageName(a).localeCompare(languageName(b)));
  if (langs.length === 0) return <p className="muted small">No terms yet.</p>;
  return (
    <div className="terms-read">
      {langs.map((l) => (
        <div key={l} className="terms-read-group">
          <span className="micro muted">{languageName(l)}</span>
          <ul>
            {(byLang.get(l) ?? []).map((t) => (
              <li key={t.id}>
                <span dir="auto" lang={l} className="term-word">
                  {t.term}
                </span>{' '}
                <span className="muted small">
                  {TERM_KIND_LABEL[t.kind]} · {MODE_LABEL[t.mode]}
                  {t.country_code ? ` · ${idx.nameOf(t.country_code)} only` : ''}
                  {t.exclusions.length ? ` · never: ${t.exclusions.join(', ')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function IngredientsPage() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const idx = useCountryIndex();
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const list = useQuery({
    queryKey: ['ingredients'],
    queryFn: async () => {
      const rows =
        unwrap<Omit<IngredientWithTerms, 'confirmed_by_person'>[] | null>(
          await supabase
            .from('ingredient')
            .select(
              'id,inn_en,atc_code,wikidata_qid,rxcui,active,confirmed_by,confirmed_at,created_at,' +
                'ingredient_term(id,ingredient_id,lang,country_code,term,kind,mode,exclusions,source,verified_by,verified_at)',
            )
            .order('inn_en'),
        ) ?? [];
      // Who confirmed it: from person_directory, because the person table shows a non-admin only their own row.
      const names = await personNames(rows.map((r) => r.confirmed_by));
      return rows.map((r): IngredientWithTerms => {
        const name = r.confirmed_by ? names.get(r.confirmed_by) : undefined;
        return { ...r, confirmed_by_person: name ? { full_name: name } : null };
      });
    },
  });

  const setActive = useMutation({
    mutationFn: async ({ id, active }: { id: string; active: boolean }) => {
      unwrap<null>(await supabase.from('ingredient').update({ active }).eq('id', id));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ingredients'] }),
  });

  const existingAtc = useMemo(
    () => new Set((list.data ?? []).map((i) => i.atc_code).filter((x): x is string => Boolean(x))),
    [list.data],
  );

  return (
    <div className="page">
      <PageHead
        eyebrow="Watchlist"
        title="Ingredients"
        lede="Each ingredient is looked for under every name it carries, in each regulator’s own language."
        actions={
          isAdmin && !adding ? (
            <Button
              variant="primary"
              onClick={() => {
                setAdding(true);
                setSaved(false);
              }}
            >
              Add ingredient
            </Button>
          ) : null
        }
      />

      {adding ? (
        <AddIngredient
          existingAtc={existingAtc}
          onDone={() => {
            setAdding(false);
            setSaved(true);
          }}
        />
      ) : null}
      {saved && !adding ? <Notice tone="ok">The watchlist is up to date.</Notice> : null}
      {setActive.isError ? <Notice tone="error">Not changed: {errorMessage(setActive.error)}</Notice> : null}

      {list.isPending ? (
        <Loading label="Reading the watchlist" />
      ) : list.isError ? (
        <ErrorNote title="The watchlist could not be loaded." error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.length === 0 ? (
        <Empty title="The watchlist is empty.">
          <p>
            {isAdmin
              ? 'Add the first ingredient. PHAROS gathers its names in every language for you to check.'
              : 'An administrator adds the ingredients to watch.'}
          </p>
        </Empty>
      ) : (
        <Table className="ingredients">
          <thead>
            <tr>
              <th scope="col">Ingredient</th>
              <th scope="col">ATC code</th>
              <th scope="col" className="num">
                Terms
              </th>
              <th scope="col">Languages</th>
              <th scope="col">Country-specific names</th>
              <th scope="col">Confirmed</th>
              <th scope="col">Watched</th>
            </tr>
          </thead>
          <tbody>
            {list.data.map((i) => {
              const langs = [...new Set(i.ingredient_term.map((t) => t.lang))].map(languageName).sort();
              const ctry = [...new Set(i.ingredient_term.map((t) => t.country_code).filter((c): c is string => Boolean(c)))]
                .map((c) => idx.nameOf(c))
                .sort();
              const isOpen = open === i.id;
              return (
                <Fragment key={i.id}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="link-button strong"
                        aria-expanded={isOpen}
                        onClick={() => setOpen(isOpen ? null : i.id)}
                      >
                        {i.inn_en}
                      </button>
                    </td>
                    <td className="mono">{i.atc_code ?? '—'}</td>
                    <td className="num mono">{i.ingredient_term.length}</td>
                    <td className="small">{langs.join(', ') || '—'}</td>
                    <td className="small">{ctry.join(', ') || '—'}</td>
                    <td className="small">
                      {i.confirmed_at ? (
                        <>
                          {i.confirmed_by_person?.full_name ?? 'Someone'}, <span className="mono">{formatCairoDate(i.confirmed_at)}</span>
                        </>
                      ) : (
                        <Tag tone="quiet">Not confirmed</Tag>
                      )}
                    </td>
                    <td>
                      {isAdmin ? (
                        <Toggle
                          checked={i.active}
                          disabled={setActive.isPending}
                          onChange={(v) => setActive.mutate({ id: i.id, active: v })}
                          label={i.active ? 'Yes' : 'Paused'}
                        />
                      ) : (
                        <span>{i.active ? 'Yes' : 'Paused'}</span>
                      )}
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr className="row-detail">
                      <td colSpan={7}>
                        <TermsList terms={i.ingredient_term} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </Table>
      )}
    </div>
  );
}
