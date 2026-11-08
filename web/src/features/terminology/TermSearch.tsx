import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { ErrorNote } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { MATCH_LABEL, SOURCE_LABEL, TERM_SOURCES, conceptPath, type TermHit, type TermSource } from './terms';
import { useTermSearch } from './useTerms';

/** One chip per source: none chosen searches them all. */
export function SourceChips({ value, onChange }: { value: TermSource[]; onChange: (v: TermSource[]) => void }) {
  return (
    <div className="term-chips" role="group" aria-label="Sources">
      {TERM_SOURCES.map((s) => {
        const on = value.includes(s);
        return (
          <button
            key={s}
            type="button"
            className={on ? 'term-chip is-on' : 'term-chip'}
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== s) : [...value, s])}
          >
            {SOURCE_LABEL[s]}
          </button>
        );
      })}
    </div>
  );
}

/** A hit: the source, the name, the words it was found as when they differ, and the code. */
export function HitLine({ h, link = true }: { h: TermHit; link?: boolean }) {
  return (
    <span className="code-name">
      <Tag tone={h.source === 'icd11' ? 'neutral' : 'blue'}>{SOURCE_LABEL[h.source]}</Tag>{' '}
      {link ? <Link to={conceptPath(h.source, h.code)}>{h.name}</Link> : h.name}{' '}
      <span className="code-sub mono">{h.code}</span>
      {h.status === 'retired' ? (
        <>
          {' '}
          <Tag tone="warning">Retired</Tag>
        </>
      ) : null}
      {h.chosen_before ? (
        <>
          {' '}
          <Tag tone="success">
            Chosen before on {h.chosen_before} case{h.chosen_before === 1 ? '' : 's'}
          </Tag>
        </>
      ) : null}
      {h.found_as && h.found_as !== h.name ? <span className="code-sub">found as “{h.found_as}”</span> : null}
      <span className="code-sub">by {MATCH_LABEL[h.match]}</span>
    </span>
  );
}

/**
 * The search of every free terminology (debounced, like the MeSH search on the case page): a code finds its
 * concept; words find the exact name, then the start of a name, then close spellings.
 */
export function TermSearch({
  onChoose,
  initial = '',
  chooseLabel = 'Use',
  autoFocus = false,
}: {
  onChoose?: (h: TermHit) => void;
  initial?: string;
  chooseLabel?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState(initial);
  const [sources, setSources] = useState<TermSource[]>([]);
  const hits = useTermSearch(text, sources);
  const q = text.trim();
  return (
    <div className="code-search term-search">
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Words or a code (NCIt C…, OAE_…, ICD-11, MeSH D…), in English or Arabic"
        aria-label="Search the free terminologies"
        autoFocus={autoFocus}
      />
      <SourceChips value={sources} onChange={setSources} />
      {hits.error ? <ErrorNote error={hits.error} title="The search did not answer." /> : null}
      {q.length >= 2 && hits.data ? (
        hits.data.length ? (
          <ul className="code-list">
            {hits.data.map((h) => (
              <li key={`${h.source}:${h.code}`}>
                <HitLine h={h} />
                {onChoose ? (
                  <Button size="sm" onClick={() => onChoose(h)}>
                    {chooseLabel}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="code-sub">Nothing in {sources.length ? sources.map((s) => SOURCE_LABEL[s]).join(', ') : 'the free terminologies'} is close to these words.</p>
        )
      ) : null}
    </div>
  );
}
