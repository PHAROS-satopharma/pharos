import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { supabase } from '../../lib/supabase';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDate, formatDateTime } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { DOC_TYPE_LABEL, METHOD_LABEL } from '../../lib/labels';
import type { IssueCopy } from './queries';
import { Button } from '../../ui/Button';
import { Country } from '../../ui/Flag';
import { Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { cx } from '../../ui/cx';

function CopyActions({ issueId, copy }: { issueId: string; copy: IssueCopy }) {
  const { person } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [confirmSplit, setConfirmSplit] = useState(false);
  const docId = copy.document?.id ?? '';

  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['issue-copies', issueId] }),
      qc.invalidateQueries({ queryKey: ['issue', issueId] }),
      qc.invalidateQueries({ queryKey: ['issue-evidence', issueId] }),
      qc.invalidateQueries({ queryKey: ['issues'] }),
    ]);
  };

  const confirm = useMutation({
    mutationFn: async () => {
      unwrap<null>(
        await supabase
          .from('issue_document')
          .update({ method: 'manual', linked_by: person?.id ?? null, linked_at: new Date().toISOString() })
          .eq('issue_id', issueId)
          .eq('document_id', docId),
      );
    },
    onSuccess: refresh,
  });

  // The copy becomes a notification of its own; the page moves to it.
  const split = useMutation({
    mutationFn: async () =>
      unwrap<string>(await supabase.rpc('split_issue_document', { p_issue: issueId, p_document: docId })),
    onSuccess: async (newId) => {
      await refresh();
      if (newId) navigate(`/issue/${newId}`);
    },
  });

  return (
    <div className="copy-actions">
      {copy.method === 'suggested' ? (
        <Button size="sm" variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>
          Confirm it is the same notice
        </Button>
      ) : null}
      {copy.link !== 'anchor' ? (
        confirmSplit ? (
          <span className="inline-confirm">
            <span className="small">Make this copy a notification of its own?</span>
            <Button size="sm" variant="danger" busy={split.isPending} onClick={() => split.mutate()}>
              Yes, split it off
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setConfirmSplit(false)}>
              Keep it
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setConfirmSplit(true)}>
            Split
          </Button>
        )
      ) : null}
      {confirm.isError ? <Notice tone="error">Not confirmed: {errorMessage(confirm.error)}</Notice> : null}
      {split.isError ? <Notice tone="error">Not split: {errorMessage(split.error)}</Notice> : null}
    </div>
  );
}

export function PublishedIn({ issueId, copies }: { issueId: string; copies: IssueCopy[] }) {
  const { canReview } = useAuth();
  if (copies.length === 0) {
    return <p className="soft">No published copy is linked to this notification.</p>;
  }
  return (
    <ul className="copies">
      {copies.map((c) => {
        const d = c.document;
        if (!d) return null;
        const reg = d.source?.regulator ?? null;
        return (
          <li key={d.id} className={cx('copy', c.link === 'anchor' && 'is-anchor')}>
            <div className="copy-where">
              <Country name={reg?.country_name ?? null} code={reg?.country_code ?? null} />
              <span className="copy-regulator">{reg?.name ?? 'Unknown regulator'}</span>
              <span className="copy-date">{formatDate(d.published_date)}</span>
            </div>
            <div className="copy-body">
              <a
                href={safeHref(d.url) ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                className="copy-title"
                dir="auto"
                lang={d.lang ?? undefined}
              >
                {d.title_orig} <span aria-hidden>↗</span>
              </a>
              <div className="copy-meta">
                <span>{DOC_TYPE_LABEL[d.doc_type]}</span>
                {c.link === 'anchor' ? <Tag tone="blue">First published here</Tag> : null}
                <Tag
                  tone={c.method === 'suggested' ? 'warning' : 'neutral'}
                  title={
                    c.method === 'manual' && c.linked_by_person
                      ? `${c.linked_by_person.full_name}, ${formatDateTime(c.linked_at)}`
                      : c.score != null
                        ? `Match score ${c.score}`
                        : undefined
                  }
                >
                  {METHOD_LABEL[c.method]}
                </Tag>
                {d.is_backfill ? <Tag tone="quiet">History</Tag> : null}
              </div>
              {canReview ? <CopyActions issueId={issueId} copy={c} /> : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
