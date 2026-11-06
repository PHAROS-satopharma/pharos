import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Tag } from '../../ui/Tag';
import { SUGGESTION_FROM, type DrugSuggestion, type MeshSuggestion } from './caseForm';

/**
 * Coding on the case page (migration 0061): the code chosen, the coder's suggestions with their reasons, and a
 * search of MeSH. A suggestion is only ever a proposal: the reviewer presses "Use" and the code goes into the
 * form, which is saved and confirmed as before.
 */

interface MeshHit {
  ui: string;
  name: string;
  term: string;
  categories: string[];
}

function useDebounced(value: string, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function MeshSearch({ onChoose }: { onChoose: (ui: string, name: string) => void }) {
  const [text, setText] = useState('');
  const q = useDebounced(text.trim());
  const hits = useQuery({
    queryKey: ['mesh-search', q],
    queryFn: async () => unwrap<MeshHit[]>(await supabase.rpc('mesh_search', { p_text: q, p_limit: 8 })),
    enabled: q.length >= 3,
    staleTime: 5 * 60_000,
  });
  return (
    <div className="code-search">
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search MeSH (at least 3 letters)"
        aria-label="Search MeSH"
      />
      {q.length >= 3 && hits.data ? (
        hits.data.length ? (
          <ul className="code-list">
            {hits.data.map((h) => (
              <li key={h.ui}>
                <span className="code-name">
                  {h.name}
                  {h.term !== h.name ? <span className="code-sub"> found as “{h.term}”</span> : null}
                  <span className="code-sub">{h.categories.join(' · ')}</span>
                </span>
                <Button size="sm" onClick={() => onChoose(h.ui, h.name)}>
                  Use
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="code-sub">No MeSH name is close to these words.</p>
        )
      ) : null}
    </div>
  );
}

/** One set of words coded with MeSH: a reaction, an indication or a medical-history condition. */
export function MeshCoding({
  label,
  ui,
  term,
  suggestions,
  editable,
  onChoose,
}: {
  label: string;
  ui: string | null | undefined;
  term: string | null | undefined;
  suggestions: MeshSuggestion[] | null;
  editable: boolean;
  onChoose: (ui: string | null, name: string | null) => void;
}) {
  const [searching, setSearching] = useState(false);
  const others = (suggestions ?? []).filter((s) => s.ui !== ui);
  return (
    <div className="code-box">
      <div className="code-head">
        <span className="code-label">{label}</span>
        {ui ? (
          <span className="code-chosen">
            <Tag tone="blue">MeSH</Tag> {term} <span className="code-sub">{ui}</span>
          </span>
        ) : (
          <span className="code-sub">Not coded yet</span>
        )}
        {editable && ui ? (
          <Button size="sm" variant="quiet" onClick={() => onChoose(null, null)}>
            Remove the code
          </Button>
        ) : null}
      </div>
      {editable && others.length ? (
        <ul className="code-list">
          {others.map((s) => (
            <li key={s.ui}>
              <span className="code-name">
                <Tag tone={s.from === 'memory' ? 'success' : s.from === 'reader' ? 'blue' : 'quiet'}>
                  {SUGGESTION_FROM[s.from]}
                </Tag>{' '}
                {s.name}
                <span className="code-sub">{s.categories.join(' · ')}</span>
                <span className="code-why">{s.reason}</span>
              </span>
              <Button size="sm" onClick={() => onChoose(s.ui, s.name)}>
                Use
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {editable && suggestions === null ? (
        <p className="code-sub">No suggestions for these words yet: press “Suggest the codes again” after saving.</p>
      ) : null}
      {editable ? (
        searching ? (
          <MeshSearch
            onChoose={(u, n) => {
              onChoose(u, n);
              setSearching(false);
            }}
          />
        ) : (
          <Button size="sm" variant="quiet" onClick={() => setSearching(true)}>
            Search MeSH
          </Button>
        )
      ) : null}
    </div>
  );
}

/** A product coded at the ingredient level with RxNorm, and its ingredients' UNII. */
export function DrugCoding({
  rxcui,
  name,
  unii,
  suggestions,
  editable,
  onChoose,
}: {
  rxcui: string | null | undefined;
  name: string | null | undefined;
  unii: string | null | undefined;
  suggestions: DrugSuggestion[] | null;
  editable: boolean;
  onChoose: (s: DrugSuggestion | null) => void;
}) {
  const others = (suggestions ?? []).filter((s) => s.rxcui !== rxcui || !s.rxcui);
  return (
    <div className="code-box">
      <div className="code-head">
        <span className="code-label">Product code</span>
        {name ? (
          <span className="code-chosen">
            <Tag tone="blue">RxNorm</Tag> {name}
            {rxcui ? <span className="code-sub">RxCUI {rxcui}</span> : null}
            {unii ? <span className="code-sub">UNII {unii}</span> : null}
          </span>
        ) : (
          <span className="code-sub">Not coded yet</span>
        )}
        {editable && name ? (
          <Button size="sm" variant="quiet" onClick={() => onChoose(null)}>
            Remove the code
          </Button>
        ) : null}
      </div>
      {editable && others.length ? (
        <ul className="code-list">
          {others.map((s) => (
            <li key={`${s.rxcui}-${s.name}`}>
              <span className="code-name">
                <Tag tone={s.from === 'memory' ? 'success' : s.from === 'watchlist' ? 'blue' : 'quiet'}>
                  {SUGGESTION_FROM[s.from]}
                </Tag>{' '}
                {s.name}
                {s.ingredients.length > 1 ? (
                  <span className="code-sub">{s.ingredients.map((i) => i.name).join(' + ')}</span>
                ) : null}
                <span className="code-why">{s.reason}</span>
              </span>
              <Button size="sm" onClick={() => onChoose(s)}>
                Use
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** What the coding stands on, as NLM's terms ask. */
export function CodingSource({ mesh }: { mesh: string | null | undefined }) {
  return (
    <p className="code-source">
      Codes: {mesh ?? 'MeSH'} and RxNorm, publicly available data of the U.S. National Library of Medicine (NLM);
      UNII from the U.S. FDA. NLM does not endorse PHAROS. MedDRA is not licensed here: its code and version are
      typed from the authority’s or a partner’s coding.
    </p>
  );
}
