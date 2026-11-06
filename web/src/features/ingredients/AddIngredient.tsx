import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, invoke, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { useCountryIndex } from '../../lib/regulators';
import { useDebounced } from '../../lib/useDebounced';
import { languageName } from '../../lib/labels';
import type { LookupCandidate, LookupTerm } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Field, Input } from '../../ui/Input';
import { Loading, Notice } from '../../ui/States';
import { cx } from '../../ui/cx';
import { TermEditor, defaultMode, newUid, type TermDraft } from './TermEditor';

function norm(s: string): string {
  return s
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '');
}

function confirmLabel(c: LookupCandidate): string {
  return c.atc_code ? `Confirm ${c.inn_en} (${c.atc_code})` : `Confirm ${c.inn_en} (no ATC code)`;
}

/**
 * The drug classes an ingredient belongs to. The lookup may name them itself (class_codes); otherwise
 * the ATC code decides: M01A and M02AA are the non-steroidal anti-inflammatory groups (NSAID).
 */
export function classCodesFor(c: LookupCandidate): string[] {
  if (Array.isArray(c.class_codes)) return c.class_codes.filter((x) => typeof x === 'string' && x !== '');
  const atc = (c.atc_code ?? '').toUpperCase();
  return atc.startsWith('M01A') || atc.startsWith('M02AA') ? ['NSAID'] : [];
}

function toDrafts(terms: LookupTerm[], inn: string): TermDraft[] {
  const seen = new Set<string>();
  const out: TermDraft[] = [];
  for (const t of terms) {
    const k = `${t.lang}|${t.term.toLowerCase()}`;
    if (!t.term || seen.has(k)) continue;
    seen.add(k);
    out.push({
      uid: newUid(),
      lang: t.lang,
      term: t.term,
      kind: t.kind ?? 'inn',
      mode: t.mode ?? defaultMode(t.lang),
      exclusions: '',
      country: t.country_code ?? '',
      source: t.source ?? 'lookup',
    });
  }
  if (!out.some((t) => t.lang === 'en')) {
    out.push({ uid: newUid(), lang: 'en', term: inn, kind: 'inn', mode: 'stem', exclusions: '', country: '', source: 'lookup' });
  }
  return out;
}

export function AddIngredient({ existingAtc, onDone }: { existingAtc: Set<string>; onDone: () => void }) {
  const { person } = useAuth();
  const qc = useQueryClient();
  const countries = useCountryIndex();
  const [typed, setTyped] = useState('');
  const q = useDebounced(typed.trim(), 350);
  const [chosen, setChosen] = useState<LookupCandidate | null>(null);
  const [confirmed, setConfirmed] = useState<LookupCandidate | null>(null);
  const [terms, setTerms] = useState<TermDraft[]>([]);
  const [termsError, setTermsError] = useState<string | null>(null);
  const [termsLoading, setTermsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const lookup = useQuery({
    queryKey: ['ingredient-lookup', q],
    enabled: q.length >= 3 && !confirmed,
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const r = await invoke<{ candidates?: LookupCandidate[] }>('ingredient-lookup', { q });
      return [...(r.candidates ?? [])].sort((a, b) => b.score - a.score);
    },
  });

  const countryOptions = useMemo(
    () =>
      countries.names
        .map((n) => ({ value: countries.codeOf(n) ?? '', label: n }))
        .filter((o) => o.value !== ''),
    [countries],
  );

  async function confirm(c: LookupCandidate) {
    setConfirmed(c);
    setTermsError(null);
    setTermsLoading(true);
    try {
      const r = await invoke<{ terms?: LookupTerm[] }>('ingredient-lookup', {
        action: 'terms',
        wikidata_qid: c.wikidata_qid,
        atc_code: c.atc_code,
        inn_en: c.inn_en,
      });
      setTerms(toDrafts(r.terms ?? [], c.inn_en));
    } catch (e) {
      setTermsError(errorMessage(e));
      setTerms(toDrafts([], c.inn_en));
    } finally {
      setTermsLoading(false);
    }
  }

  async function save() {
    if (!confirmed || !person) return;
    setSaving(true);
    setSaveError(null);
    try {
      const seen = new Set<string>();
      const termRows = terms
        .filter((t) => t.term.trim())
        .filter((t) => {
          const k = `${t.lang}|${t.term.trim()}`;
          if (seen.has(k)) return false;
          seen.add(k);
          return true;
        })
        .map((t) => ({
          lang: t.lang,
          country_code: t.country || null,
          term: t.term.trim(),
          kind: t.kind,
          mode: t.mode,
          exclusions: t.exclusions
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean),
          source: t.source || 'manual',
        }));
      // One step in the database: the ingredient, its terms and its classes are saved together or not at all.
      unwrap<string>(
        await supabase.rpc('save_ingredient', {
          p: {
            inn_en: confirmed.inn_en,
            atc_code: confirmed.atc_code,
            wikidata_qid: confirmed.wikidata_qid,
            rxcui: confirmed.rxcui,
            class_codes: classCodesFor(confirmed),
            terms: termRows,
          },
        }),
      );
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['ingredients'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-names'] }),
        qc.invalidateQueries({ queryKey: ['ingredient-list'] }),
      ]);
      onDone();
    } catch (e) {
      setSaveError(`Not saved: ${errorMessage(e)}`);
    } finally {
      setSaving(false);
    }
  }

  // Step 2: the term editor, after the ingredient is confirmed.
  if (confirmed) {
    const count = terms.filter((t) => t.term.trim()).length;
    return (
      <section className="panel add-panel" aria-labelledby="add-ing-title">
        <div className="panel-head">
          <h2 id="add-ing-title" className="panel-title">
            Terms for {confirmed.inn_en}
            {confirmed.atc_code ? <span className="mono soft"> · {confirmed.atc_code}</span> : null}
          </h2>
          <Button
            size="sm"
            variant="quiet"
            onClick={() => {
              setConfirmed(null);
              setTerms([]);
            }}
          >
            Choose a different ingredient
          </Button>
        </div>
        <p className="small muted">
          These are the words PHAROS looks for in each regulator’s own language. Check them, add brand names, and test
          each against the archive. Nothing is saved until you press Save.
        </p>
        <p className="small muted">
          After saving, the next daily run adds its group from the ATC code (searched) and the class above it (shown,
          switched off until you have read its words), and starts checking the notices PHAROS already holds from the
          last 12 months for these names, as history (no messages). The search profile is set on the ingredient’s line.
        </p>
        {classCodesFor(confirmed).includes('NSAID') ? (
          <p className="small">
            Saved as an <strong>NSAID</strong>: notices that name only the class (for example “NSAR-haltige
            Arzneimittel”) reach the daily digest, not an immediate message.
          </p>
        ) : null}
        {termsError ? (
          <Notice tone="error">The suggested terms could not be loaded ({termsError}). Add them by hand.</Notice>
        ) : null}
        {termsLoading ? (
          <Loading label="Gathering the names in each language" />
        ) : (
          <TermEditor terms={terms} onChange={setTerms} languages={countries.languages} countries={countryOptions} />
        )}
        {saveError ? <Notice tone="error">{saveError}</Notice> : null}
        <div className="panel-foot">
          <Button variant="primary" busy={saving} disabled={count === 0 || termsLoading} onClick={() => void save()}>
            Save {confirmed.inn_en} with {count} {count === 1 ? 'term' : 'terms'}
          </Button>
          <Button variant="quiet" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </section>
    );
  }

  // Step 1: find the ingredient and confirm which one is meant.
  const candidates = lookup.data ?? [];
  const already = chosen?.atc_code ? existingAtc.has(chosen.atc_code) : false;
  const differs = chosen ? norm(typed) !== norm(chosen.inn_en) : false;

  return (
    <section className="panel add-panel" aria-labelledby="add-ing-title">
      <div className="panel-head">
        <h2 id="add-ing-title" className="panel-title">
          Add an ingredient
        </h2>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <Field label="Ingredient name" hint="Any language or spelling. At least three letters.">
        <Input
          value={typed}
          autoFocus
          onChange={(e) => {
            setTyped(e.target.value);
            setChosen(null);
          }}
          placeholder="e.g. lornoxicam"
          dir="auto"
        />
      </Field>

      {q.length >= 3 ? (
        lookup.isPending ? (
          <Loading label="Looking it up" />
        ) : lookup.isError ? (
          <Notice tone="error">The lookup did not answer: {errorMessage(lookup.error)}</Notice>
        ) : candidates.length === 0 ? (
          <p className="muted">Nothing found for “{q}”. Check the spelling, or try the name in English.</p>
        ) : (
          <ul className="candidates" aria-label="Possible ingredients">
            {candidates.map((c) => {
              const labels = Object.entries(c.labels ?? {}).slice(0, 8);
              const selected = chosen?.inn_en === c.inn_en && chosen?.atc_code === c.atc_code;
              return (
                <li key={`${c.inn_en}-${c.atc_code ?? c.wikidata_qid ?? ''}`}>
                  <button
                    type="button"
                    className={cx('candidate', selected && 'is-selected')}
                    aria-pressed={selected}
                    onClick={() => setChosen(c)}
                  >
                    <span className="candidate-name">{c.inn_en}</span>
                    <span className="mono small">{c.atc_code ?? 'No ATC code'}</span>
                    {labels.length > 0 ? (
                      <span className="candidate-labels">
                        {labels.map(([lang, label]) => (
                          <span key={lang} className="candidate-label">
                            <span className="muted">{languageName(lang)}</span>{' '}
                            <span dir="auto" lang={lang}>
                              {label}
                            </span>
                          </span>
                        ))}
                      </span>
                    ) : null}
                    {c.sources?.length ? <span className="muted small">From {c.sources.join(', ')}</span> : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )
      ) : null}

      {chosen ? (
        <div className="confirm-box">
          {differs ? (
            <p>
              Did you mean <strong>{chosen.inn_en}</strong>? You typed “{typed.trim()}”.
            </p>
          ) : null}
          {already ? (
            <Notice tone="info">{chosen.inn_en} is already on the watchlist.</Notice>
          ) : (
            <Button variant="primary" onClick={() => void confirm(chosen)}>
              {confirmLabel(chosen)}
            </Button>
          )}
        </div>
      ) : null}
    </section>
  );
}
