import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import '../../styles/cases.css';
import '../../styles/terminology.css';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDate } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Input } from '../../ui/Input';
import { Empty, ErrorNote, Loading, Notice } from '../../ui/States';
import { Table } from '../../ui/Table';
import { Tag } from '../../ui/Tag';
import { PageHead, SectionHead } from '../../ui/Text';
import { TermSearch } from './TermSearch';
import {
  SOURCE_CREDIT,
  SOURCE_LABEL,
  TERM_SOURCES,
  conceptPath,
  ctcaeGrades,
  isTermSource,
  type TermChange,
  type TermChild,
  type TermPathStep,
  type TermRelated,
  type TermRelease,
  type TermSource,
} from './terms';
import { lookupTerm } from './useTerms';

/**
 * The free terminologies (migration 0103): one search over NCI Thesaurus, OAE, ICD-11 and MeSH, the page of each
 * concept, and for an administrator the review of each new release before it is used.
 */
export function TerminologyPage() {
  const { source, code } = useParams();
  const { isAdmin } = useAuth();
  const concept = isTermSource(source) && code ? { source, code: decodeURIComponent(code) } : null;
  return (
    <div className="page terminology-page">
      <PageHead
        eyebrow="Pharmacovigilance"
        title="Terminology"
        lede="Free medical terminologies, searched together: NCI Thesaurus (with CTCAE), the Ontology of Adverse Events, WHO ICD-11 in English and Arabic, and MeSH. None of them is MedDRA: they name and group a reaction until it is coded with an official MedDRA LLT."
      />
      <section className="panel">
        <SectionHead index="01" title="Search" />
        <TermSearch autoFocus={!concept} />
      </section>
      {concept ? (
        <section className="panel">
          <SectionHead index="02" title="Concept" />
          <ConceptView source={concept.source} code={concept.code} />
        </section>
      ) : null}
      <section className="panel">
        <SectionHead index={concept ? '03' : '02'} title="Releases" />
        <Releases isAdmin={isAdmin} />
      </section>
      <section className="panel">
        <SectionHead index={concept ? '04' : '03'} title="What these are, and are not" />
        <ul className="term-credits">
          {TERM_SOURCES.map((s) => (
            <li key={s}>{SOURCE_CREDIT[s]}.</li>
          ))}
        </ul>
        <p className="code-source">
          MedDRA is the dictionary the E2B(R3) file and the authorities require; it is licensed by ICH through MSSO.
          These terminologies do not replace it and no code here is an official MedDRA code or mapping. “Same words”
          links between sources are only that.
        </p>
      </section>
    </div>
  );
}

function ConceptView({ source, code }: { source: TermSource; code: string }) {
  const concept = useQuery({
    queryKey: ['term-concept', source, code],
    queryFn: () => lookupTerm(source, code),
  });
  const path = useQuery({
    queryKey: ['term-path', source, code],
    queryFn: async () => unwrap<TermPathStep[]>(await supabase.rpc('term_path', { p_source: source, p_code: code })),
  });
  const children = useQuery({
    queryKey: ['term-children', source, code],
    queryFn: async () => unwrap<TermChild[]>(await supabase.rpc('term_children', { p_source: source, p_code: code })),
  });
  const related = useQuery({
    queryKey: ['term-related', source, code],
    queryFn: async () => unwrap<TermRelated[]>(await supabase.rpc('term_related', { p_source: source, p_code: code })),
  });
  const grades = ctcaeGrades(children.data ?? []);
  const gradeText = useQuery({
    queryKey: ['term-grades', source, code, grades.map((g) => g.code).join(',')],
    queryFn: async () =>
      unwrap<{ code: string; definition: string | null }[]>(
        await supabase.from('term_concept').select('code, definition').eq('source', source).in('code', grades.map((g) => g.code)),
      ),
    enabled: grades.length > 0,
  });

  if (concept.isLoading) return <Loading label="Opening the concept" />;
  if (concept.error) return <ErrorNote error={concept.error} onRetry={() => void concept.refetch()} />;
  const c = concept.data;
  if (!c) {
    return (
      <Empty title={`${SOURCE_LABEL[source]} has no concept ${code}.`}>
        <p>The code may be mistyped, or not in the part of {SOURCE_LABEL[source]} PHAROS keeps.</p>
      </Empty>
    );
  }
  const others = c.names.filter((n) => !(n.preferred && n.lang === c.lang));
  const steps = (path.data ?? []).filter((p) => p.code !== c.code);
  const definitions = new Map((gradeText.data ?? []).map((g) => [g.code, g.definition]));
  return (
    <div className="term-concept">
      <h2 className="term-name">
        {c.name} <span className="code-sub mono">{c.code}</span>
      </h2>
      <p>
        <Tag tone="blue">{c.source_name}</Tag> {c.status === 'retired' ? <Tag tone="warning">Retired{c.retired_in ? ` in ${c.retired_in}` : ''}</Tag> : null}{' '}
        <span className="code-sub">
          Release {c.version ?? 'not active'} · {c.licence} ·{' '}
          <a href={c.licence_url} target="_blank" rel="noreferrer">
            licence
          </a>
          {c.uri ? (
            <>
              {' '}
              ·{' '}
              <a href={c.uri} target="_blank" rel="noreferrer">
                at the source
              </a>
            </>
          ) : null}
        </span>
      </p>
      {steps.length ? (
        <nav className="term-path" aria-label="Path">
          {steps.map((p) => (
            <span key={p.code}>
              <Link to={conceptPath(source, p.code)}>{p.name}</Link>
              <span aria-hidden> › </span>
            </span>
          ))}
          <span>{c.name}</span>
        </nav>
      ) : null}
      {c.definition ? <p className="term-definition">{c.definition}</p> : <p className="code-sub">No definition in {c.source_name}.</p>}
      {others.length ? (
        <>
          <h3 className="term-h">Other names</h3>
          <ul className="term-names">
            {others.map((n) => (
              <li key={`${n.lang}:${n.name}`} lang={n.lang} dir={n.lang === 'ar' ? 'rtl' : undefined}>
                {n.name}
                {n.lang !== 'en' ? <span className="code-sub"> {n.lang}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {grades.length ? (
        <>
          <h3 className="term-h">CTCAE grades</h3>
          <Table>
            <thead>
              <tr>
                <th>Grade</th>
                <th>Criteria</th>
              </tr>
            </thead>
            <tbody>
              {grades.map((g) => (
                <tr key={g.code}>
                  <td>
                    <Link to={conceptPath(source, g.code)}>{g.grade}</Link>
                  </td>
                  <td>{definitions.get(g.code) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      ) : null}
      {children.data && children.data.length > grades.length ? (
        <>
          <h3 className="term-h">Narrower concepts</h3>
          <ul className="term-names">
            {children.data
              .filter((k) => !grades.some((g) => g.code === k.code))
              .map((k) => (
                <li key={k.code}>
                  <Link to={conceptPath(source, k.code)}>{k.name}</Link>{' '}
                  {k.status === 'retired' ? <Tag tone="warning">Retired</Tag> : null}
                  {k.children ? <span className="code-sub"> {k.children} under it</span> : null}
                </li>
              ))}
          </ul>
        </>
      ) : null}
      {related.data?.length ? (
        <>
          <h3 className="term-h">Same words in another source</h3>
          <ul className="term-names">
            {related.data.map((r) => (
              <li key={`${r.source}:${r.code}`}>
                <Tag tone="quiet">{SOURCE_LABEL[r.source]}</Tag> <Link to={conceptPath(r.source, r.code)}>{r.name}</Link>{' '}
                <span className="code-sub">
                  {r.code} · {r.note}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <p className="code-source">{c.attribution}</p>
    </div>
  );
}

const STATUS_TAG: Record<TermRelease['status'], { tone: 'success' | 'warning' | 'quiet' | 'danger'; label: string }> = {
  active: { tone: 'success', label: 'In use' },
  staged: { tone: 'warning', label: 'Waiting for review' },
  superseded: { tone: 'quiet', label: 'Replaced' },
  rejected: { tone: 'danger', label: 'Rejected' },
};

const RELEASES_KEY = ['term-releases'];

function Releases({ isAdmin }: { isAdmin: boolean }) {
  const releases = useQuery({
    queryKey: RELEASES_KEY,
    queryFn: async () =>
      unwrap<TermRelease[]>(
        await supabase
          .from('term_release')
          .select('id, source, version, url, status, concepts, names, added, changed, retired, fetched_at, activated_at, note')
          .order('id', { ascending: false })
          .limit(20),
      ),
  });
  if (releases.isLoading) return <Loading label="Reading the releases" />;
  if (releases.error) return <ErrorNote error={releases.error} onRetry={() => void releases.refetch()} />;
  const rows = releases.data ?? [];
  if (!rows.length) {
    return (
      <Empty title="No terminology is loaded yet.">
        <p>
          The “PHAROS dictionaries” workflow loads them on the 3rd of each month, or by hand (Terminology: all).
        </p>
      </Empty>
    );
  }
  const staged = rows.filter((r) => r.status === 'staged');
  return (
    <>
      {staged.map((r) => (
        <StagedRelease key={r.id} release={r} isAdmin={isAdmin} />
      ))}
      <Table>
        <thead>
          <tr>
            <th>Source</th>
            <th>Release</th>
            <th>Status</th>
            <th>Concepts</th>
            <th>Changes</th>
            <th>Downloaded</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{SOURCE_LABEL[r.source] ?? r.source}</td>
              <td className="mono">{r.version}</td>
              <td>
                <Tag tone={STATUS_TAG[r.status].tone}>{STATUS_TAG[r.status].label}</Tag>
                {r.note ? <span className="code-sub">{r.note}</span> : null}
              </td>
              <td>{r.concepts.toLocaleString('en-GB')}</td>
              <td>
                {r.added || r.changed || r.retired ? `+${r.added} · ~${r.changed} · −${r.retired}` : '—'}
              </td>
              <td>{formatDate(r.fetched_at)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}

const KIND_LABEL: Record<TermChange['kind'], string> = { added: 'Added', changed: 'Changed', retired: 'Retired' };

/** A release waiting for review: what it changes, and for an administrator Activate or Reject. */
function StagedRelease({ release, isAdmin }: { release: TermRelease; isAdmin: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const changes = useQuery({
    queryKey: ['term-changes', release.id],
    queryFn: async () =>
      unwrap<TermChange[]>(
        await supabase.from('term_change').select('code, kind, before, after').eq('release', release.id).order('kind').order('code').limit(60),
      ),
  });
  const done = () => {
    qc.invalidateQueries({ queryKey: RELEASES_KEY });
    qc.invalidateQueries({ queryKey: ['term-search'] });
    qc.invalidateQueries({ queryKey: ['term-concept'] });
  };
  const activate = useMutation({
    mutationFn: async () => unwrap(await supabase.rpc('activate_term_release', { p_release: release.id })),
    onSuccess: done,
  });
  const reject = useMutation({
    mutationFn: async () => unwrap(await supabase.rpc('reject_term_release', { p_release: release.id, p_note: note || null })),
    onSuccess: done,
  });
  const failed = activate.error ?? reject.error;
  const total = release.added + release.changed + release.retired;
  return (
    <div className="term-staged">
      <p>
        <Tag tone="warning">Waiting for review</Tag> {SOURCE_LABEL[release.source]} {release.version}: {release.added} added,{' '}
        {release.changed} changed, {release.retired} retired. Nothing changes in the search until it is activated.
      </p>
      {changes.data?.length ? (
        <ul className="term-names">
          {changes.data.map((c) => (
            <li key={c.code}>
              <Tag tone={c.kind === 'retired' ? 'danger' : c.kind === 'added' ? 'success' : 'quiet'}>{KIND_LABEL[c.kind]}</Tag>{' '}
              <span className="mono">{c.code}</span> {c.after?.name ?? c.before?.name}
              {c.kind === 'changed' && c.before?.name && c.after?.name && c.before.name !== c.after.name ? (
                <span className="code-sub"> was “{c.before.name}”</span>
              ) : null}
            </li>
          ))}
          {total > (changes.data?.length ?? 0) ? <li className="code-sub">… and {total - changes.data.length} more</li> : null}
        </ul>
      ) : null}
      {isAdmin ? (
        <div className="term-review">
          <Button variant="primary" busy={activate.isPending} disabled={reject.isPending} onClick={() => activate.mutate()}>
            Activate
          </Button>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why it is rejected (optional)" aria-label="Why it is rejected" />
          <Button variant="danger" busy={reject.isPending} disabled={activate.isPending} onClick={() => reject.mutate()}>
            Reject
          </Button>
        </div>
      ) : (
        <p className="code-sub">An administrator activates or rejects it.</p>
      )}
      {failed ? <Notice tone="error">{errorMessage(failed)}</Notice> : null}
    </div>
  );
}
