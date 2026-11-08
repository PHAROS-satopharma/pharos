import { useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDate } from '../../lib/format';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { HitLine, TermSearch } from './TermSearch';
import { SOURCE_LABEL, conceptPath, needsMeddra, type ReactionTerm, type TermHit } from './terms';
import { lookupTerm, useTermSearch } from './useTerms';

/** The tag a reaction carries until it has an official MedDRA LLT: the free code is never sent as MedDRA. */
export function NeedsMeddra({ reaction }: { reaction: { meddra_llt_code?: string | null } }) {
  return needsMeddra(reaction) ? (
    <Tag tone="warning" title="The E2B file needs a MedDRA Lowest Level Term; until then the case goes on CIOMS I.">
      Needs official MedDRA coding
    </Tag>
  ) : null;
}

/**
 * A reaction coded with a free terminology (0103). The closest concepts for the reaction's words are proposals
 * only: nothing is written until a reviewer presses "Use", and the choice keeps who made it, when, and the
 * release it came from. A MeSH choice also fills the reaction's MeSH code.
 */
export function TermCoding({
  term,
  words,
  editable,
  onChoose,
}: {
  term: ReactionTerm | null | undefined;
  words: string;
  editable: boolean;
  onChoose: (t: ReactionTerm | null) => void;
}) {
  const { person } = useAuth();
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const proposals = useTermSearch(editable && !term ? words : '', null, 3, 'proposal');

  async function choose(h: TermHit) {
    setBusy(true);
    setProblem(null);
    try {
      const concept = await lookupTerm(h.source, h.code);
      onChoose({
        source: h.source,
        code: h.code,
        name: h.name,
        version: concept?.version ?? null,
        coded_by: person?.full_name ?? 'unknown',
        coded_at: new Date().toISOString(),
      });
      setSearching(false);
    } catch (e) {
      setProblem(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="code-box">
      <div className="code-head">
        <span className="code-label">Free terminology</span>
        {term ? (
          <span className="code-chosen">
            <Tag tone="blue">{SOURCE_LABEL[term.source] ?? term.source}</Tag>{' '}
            <Link to={conceptPath(term.source, term.code)}>{term.name}</Link>
            <span className="code-sub mono">{term.code}</span>
            <span className="code-sub">
              {term.version ? `release ${term.version}, ` : ''}chosen by {term.coded_by} on {formatDate(term.coded_at)}
            </span>
          </span>
        ) : (
          <span className="code-sub">Not coded yet</span>
        )}
        {editable && term ? (
          <Button size="sm" variant="quiet" onClick={() => onChoose(null)}>
            Remove the code
          </Button>
        ) : null}
      </div>
      {editable && !term && proposals.data?.length ? (
        <ul className="code-list" aria-label="Closest concepts">
          {proposals.data.map((h) => (
            <li key={`${h.source}:${h.code}`}>
              <HitLine h={h} />
              <Button size="sm" busy={busy} onClick={() => void choose(h)}>
                Use
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {problem ? <Notice tone="error">The code was not chosen: {problem}</Notice> : null}
      {editable ? (
        searching ? (
          <TermSearch initial={words} onChoose={(h) => void choose(h)} />
        ) : (
          <Button size="sm" variant="quiet" onClick={() => setSearching(true)}>
            Search the free terminologies
          </Button>
        )
      ) : null}
      <p className="code-sub">
        Not MedDRA, and not sent in the E2B file: it names and groups the reaction until the official LLT is coded.
      </p>
    </div>
  );
}
