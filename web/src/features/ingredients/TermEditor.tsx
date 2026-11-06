import { useState } from 'react';
import { supabase } from '../../lib/supabase';
import { errorMessage } from '../../lib/api';
import { MODE_LABEL, TERM_KIND_LABEL, languageName } from '../../lib/labels';
import { MATCH_MODES, TERM_KINDS, type MatchMode, type TermKind } from '../../lib/types';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Select, type Option } from '../../ui/Select';
import { isJapanCode } from './readiness';

/** PMDA's search form (it answers a POST only; see docs/operations.md, "Adding an ingredient"). */
const PMDA_SEARCH = 'https://www.pmda.go.jp/PmdaSearch/iyakuSearch/';

export interface TermDraft {
  uid: string;
  lang: string;
  term: string;
  kind: TermKind;
  mode: MatchMode;
  exclusions: string;
  country: string;
  source: string;
}

let seq = 0;
export function newUid(): string {
  seq += 1;
  return `t${Date.now().toString(36)}${seq}`;
}

/** The Japan code: PMDA's product code, kept as a term of kind 'code' for Japan so the label watch can find the
 *  package inserts (ingredient_term kind 'code', country JP, source 'pmda'). */
export function isJapanCodeDraft(t: TermDraft): boolean {
  return t.kind === 'code' && t.country === 'JP';
}

/** Japanese, Chinese and Korean are matched anywhere in the text; Latin scripts by word start. */
export function defaultMode(lang: string): MatchMode {
  return ['ja', 'zh', 'ko'].includes(lang.slice(0, 2)) ? 'substring' : 'stem';
}

type HitState = { busy: boolean; count?: number; error?: string };

export function TermEditor({
  terms,
  onChange,
  languages,
  countries,
}: {
  terms: TermDraft[];
  onChange: (next: TermDraft[]) => void;
  /** Languages that can be added (the regulators' languages). */
  languages: string[];
  countries: Option[];
}) {
  const [hits, setHits] = useState<Record<string, HitState>>({});
  const [addLang, setAddLang] = useState('');

  // The Japan code is a term of kind 'code' for Japan: not a name, so it is not shown among the languages.
  const japan = terms.find(isJapanCodeDraft);
  const named = terms.filter((t) => !isJapanCodeDraft(t));
  const langs = [...new Set(named.map((t) => t.lang))].sort((a, b) => languageName(a).localeCompare(languageName(b)));
  const missing = languages.filter((l) => !langs.includes(l));

  function setJapanCode(code: string) {
    if (japan) {
      update(japan.uid, { term: code });
    } else {
      onChange([
        ...terms,
        { uid: newUid(), lang: 'ja', term: code, kind: 'code', mode: 'exact', exclusions: '', country: 'JP', source: 'pmda' },
      ]);
    }
  }

  function update(uid: string, patch: Partial<TermDraft>) {
    onChange(terms.map((t) => (t.uid === uid ? { ...t, ...patch } : t)));
    if (patch.term !== undefined || patch.lang !== undefined) {
      setHits((h) => {
        const next = { ...h };
        delete next[uid];
        return next;
      });
    }
  }

  function remove(uid: string) {
    onChange(terms.filter((t) => t.uid !== uid));
  }

  function add(lang: string) {
    onChange([
      ...terms,
      { uid: newUid(), lang, term: '', kind: 'inn', mode: defaultMode(lang), exclusions: '', country: '', source: 'manual' },
    ]);
  }

  async function test(t: TermDraft) {
    if (!t.term.trim()) return;
    setHits((h) => ({ ...h, [t.uid]: { busy: true } }));
    const { data, error } = await supabase.rpc('archive_hit_count', { p_term: t.term.trim(), p_lang: t.lang });
    setHits((h) => ({
      ...h,
      [t.uid]: error ? { busy: false, error: errorMessage(error.message) } : { busy: false, count: Number(data ?? 0) },
    }));
  }

  return (
    <div className="terms">
      {langs.map((lang) => (
        <fieldset key={lang} className="term-group">
          <legend className="term-group-head">
            <span className="term-group-name">{languageName(lang)}</span>
            <span className="soft small">{named.filter((t) => t.lang === lang).length} terms</span>
          </legend>
          <div className="term-row term-row-head" aria-hidden>
            <span className="micro soft">Term, as written</span>
            <span className="micro soft">Kind</span>
            <span className="micro soft">How it matches</span>
            <span className="micro soft">Never when it is</span>
            <span className="micro soft">Country</span>
            <span />
          </div>
          {named
            .filter((t) => t.lang === lang)
            .map((t) => {
              const h = hits[t.uid];
              return (
                <div key={t.uid} className="term-row">
                  <Input
                    aria-label={`Term in ${languageName(lang)}`}
                    value={t.term}
                    dir="auto"
                    lang={lang}
                    onChange={(e) => update(t.uid, { term: e.target.value })}
                  />
                  <Select
                    aria-label="Kind"
                    value={t.kind}
                    onChange={(e) => update(t.uid, { kind: e.target.value as TermKind })}
                    options={TERM_KINDS.map((k) => ({ value: k, label: TERM_KIND_LABEL[k] }))}
                  />
                  <Select
                    aria-label="How it matches"
                    value={t.mode}
                    onChange={(e) => update(t.uid, { mode: e.target.value as MatchMode })}
                    options={MATCH_MODES.map((m) => ({ value: m, label: MODE_LABEL[m] }))}
                  />
                  <Input
                    aria-label="Exclusions, separated by commas"
                    placeholder="e.g. tenoxicam, meloxicam"
                    value={t.exclusions}
                    lang={lang}
                    onChange={(e) => update(t.uid, { exclusions: e.target.value })}
                  />
                  <Select
                    aria-label="Country"
                    value={t.country}
                    onChange={(e) => update(t.uid, { country: e.target.value })}
                    placeholder="Every country"
                    options={countries}
                  />
                  <div className="term-actions">
                    <Button size="sm" busy={h?.busy} disabled={!t.term.trim()} onClick={() => void test(t)}>
                      Test against archive
                    </Button>
                    <Button size="sm" variant="quiet" onClick={() => remove(t.uid)} aria-label={`Remove ${t.term || 'this term'}`}>
                      Remove
                    </Button>
                    {h && !h.busy ? (
                      <span className={h.error ? 'small danger' : 'small'} role="status">
                        {h.error
                          ? `Test failed: ${h.error}`
                          : h.count === 0
                            ? 'No archived notice contains it'
                            : `${h.count} archived ${h.count === 1 ? 'notice contains' : 'notices contain'} it`}
                      </span>
                    ) : null}
                  </div>
                </div>
              );
            })}
          <div className="term-group-foot">
            <Button size="sm" variant="quiet" onClick={() => add(lang)}>
              Add a term in {languageName(lang)}
            </Button>
          </div>
        </fieldset>
      ))}

      <div className="term-add-lang">
        <Select
          aria-label="Add a language"
          value={addLang}
          onChange={(e) => setAddLang(e.target.value)}
          placeholder="Add a language…"
          options={missing.map((l) => ({ value: l, label: languageName(l) }))}
        />
        <Button
          size="sm"
          disabled={!addLang}
          onClick={() => {
            add(addLang);
            setAddLang('');
          }}
        >
          Add
        </Button>
      </div>

      <fieldset className="japan-code">
        <legend className="term-group-head">
          <span className="term-group-name">Japan code</span>
          <span className="soft small">PMDA product code, for Japan’s label watch</span>
        </legend>
        <div className="japan-code-row">
          <Input
            aria-label="Japan code"
            value={japan?.term ?? ''}
            inputMode="text"
            autoCapitalize="characters"
            placeholder="e.g. 1149036"
            onChange={(e) => setJapanCode(e.target.value.toUpperCase())}
          />
          <a className="btn btn-sm" href={PMDA_SEARCH} target="_blank" rel="noreferrer">
            Open the PMDA search
          </a>
        </div>
        {japan && japan.term.trim() && !isJapanCode(japan.term) ? (
          <p className="small danger" role="status">
            A Japan code has 7 characters (for example 1149036), or 12 for the YJ code that starts with them.
          </p>
        ) : null}
        <p className="japan-code-why">
          PMDA’s search answers a form, not an address, so PHAROS cannot look the package insert up by name. Search
          the name there, open the product, and copy the code from the end of its address (…/GeneralList/
          <span className="mono">code</span>). Without it the row says so; the ingredient is still watched everywhere
          else.
        </p>
      </fieldset>
    </div>
  );
}
