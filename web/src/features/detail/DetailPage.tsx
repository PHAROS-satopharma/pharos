import { useMemo, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useCopies, useEvidence, useIssue, useNotified, useReviews, useSpcChanges, type CopyDocument } from './queries';
import { DecisionPanel } from './DecisionPanel';
import { PublishedIn } from './PublishedIn';
import { MatchedText } from './MatchedText';
import { PdfViewer } from './PdfViewer';
import { SpcDiff } from './SpcDiff';
import { CaseReport } from './CaseReport';
import { ReviewHistory, WhoWasNotified } from './History';
import { SignalPanel } from '../signals/SignalPanel';
import { useAuth } from '../../lib/auth';
import { formatDate } from '../../lib/format';
import { safeHref } from '../../lib/safeHref';
import { DOC_TYPE_LABEL } from '../../lib/labels';
import { Country } from '../../ui/Flag';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading } from '../../ui/States';
import { IngredientChips, StatusPill, Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';
import { fileNameFor } from '../../lib/download';

interface PdfFile {
  key: string;
  label: string;
  /** The name the original is saved under: its own file name, else the last part of its link. */
  filename: string;
}

function pdfName(nameOrUrl: string | null | undefined): string {
  const name = fileNameFor(nameOrUrl, 'PHAROS-notice.pdf');
  return name.toLowerCase().endsWith('.pdf') ? name : `${name}.pdf`;
}

function isPdf(mime: string | null | undefined, name: string | null | undefined): boolean {
  return (mime ?? '').toLowerCase().includes('pdf') || (name ?? '').toLowerCase().endsWith('.pdf');
}

/** Where "All notifications" goes: the list as it was left (its filters), else the plain list. */
function backTo(state: unknown): string {
  const back = (state as { back?: unknown } | null)?.back;
  return typeof back === 'string' && (back === '/' || back.startsWith('/?')) ? back : '/';
}

export function DetailPage() {
  const { id = '' } = useParams();
  const back = backTo(useLocation().state);
  const issue = useIssue(id);
  const copies = useCopies(id);
  const documents = useMemo(
    () => (copies.data ?? []).map((c) => c.document).filter((d): d is CopyDocument => d !== null),
    [copies.data],
  );
  const docIds = useMemo(() => documents.map((d) => d.id), [documents]);
  const evidence = useEvidence(id, docIds);
  const spc = useSpcChanges(id);
  const reviews = useReviews(id);
  const notified = useNotified(id);
  const { isAdmin } = useAuth();
  const [pdfKey, setPdfKey] = useState<string>('');

  const pdfs = useMemo<PdfFile[]>(() => {
    const out: PdfFile[] = [];
    for (const d of documents) {
      const where = d.source?.regulator?.name ?? 'Regulator';
      if (d.r2_key && isPdf(d.mime, d.url)) out.push({ key: d.r2_key, label: `${where}: the notice`, filename: pdfName(d.url) });
      for (const a of evidence.data?.attachments ?? []) {
        if (a.document_id === d.id && a.r2_key && isPdf(a.mime, a.filename ?? a.url)) {
          out.push({
            key: a.r2_key,
            label: `${where}: ${a.filename ?? 'attached file'}`,
            filename: pdfName(a.filename ?? a.url),
          });
        }
      }
    }
    return out;
  }, [documents, evidence.data]);

  if (issue.isPending) return <Loading label="Opening the notification" />;
  if (issue.isError) {
    return (
      <ErrorNote title="This notification could not be loaded." error={issue.error} onRetry={() => void issue.refetch()} />
    );
  }
  const row = issue.data;
  if (!row) {
    return (
      <Empty title="This notification does not exist." action={<Link to={back}>Back to the notifications</Link>}>
        <p>It may have been merged into another notification, or the link is incomplete.</p>
      </Empty>
    );
  }

  const anchor = documents.find((d) => (copies.data ?? []).some((c) => c.link === 'anchor' && c.document?.id === d.id));
  const shownPdf = pdfs.find((p) => p.key === pdfKey) ?? pdfs[0] ?? null;
  const isLabelChange = row.doc_type === 'label_change' || (spc.data?.length ?? 0) > 0;
  const link = safeHref(row.link);
  // The page's sections in order: their numbers, and the "On this page" bar that jumps to each.
  const sections: { id: string; title: string; short: string; count?: number }[] = [
    { id: 'published-in', title: 'Published in', short: 'Published in', count: copies.data?.length },
    { id: 'where-named', title: 'Where the ingredient is named', short: 'Where it is named' },
    { id: 'original', title: 'The original document', short: 'The original', count: pdfs.length || undefined },
    ...(isLabelChange ? [{ id: 'what-changed', title: 'What changed in the product information', short: 'What changed' }] : []),
  ];
  const idx = (id: string) => String(sections.findIndex((x) => x.id === id) + 1).padStart(2, '0');

  return (
    <div className="page detail">
      <header className="detail-head masthead">
        <Link to={back} className="back-link">
          <span aria-hidden>←</span> All notifications
        </Link>
        <div className="detail-eyebrow">
          <span className="eyebrow">
            <span className="eyebrow-rule" aria-hidden />
            {DOC_TYPE_LABEL[row.doc_type]}
          </span>
          <span className="soft small">First published {formatDate(row.first_date)}</span>
          {row.class_only ? <Tag tone="quiet">Class-wide</Tag> : null}
          {row.is_backfill ? <Tag tone="quiet">History</Tag> : null}
        </div>
        <h1 className="detail-title" dir="auto" lang={anchor?.lang ?? undefined}>
          {row.title}
        </h1>
        <dl className="detail-facts">
          <div className="detail-fact">
            <dt>Status</dt>
            <dd>
              <StatusPill status={row.status} />
            </dd>
          </div>
          <div className="detail-fact">
            <dt>First published by</dt>
            <dd>
              <Country name={row.anchor_country} />
              <span className="detail-fact-sub">{row.anchor_regulator ?? '—'}</span>
            </dd>
          </div>
          <div className="detail-fact">
            <dt>Ingredient</dt>
            <dd>
              <IngredientChips ingredients={row.ingredients} classOnly={row.class_only} />
            </dd>
          </div>
          <div className="detail-fact">
            <dt>Original</dt>
            <dd>
              {link ? (
                <a href={link} target="_blank" rel="noopener noreferrer" className="ext-link">
                  On the regulator’s site <span aria-hidden>↗</span>
                </a>
              ) : (
                '—'
              )}
            </dd>
          </div>
        </dl>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <nav className="detail-toc" aria-label="On this page">
            {sections.map((x) => (
              <a
                key={x.id}
                href={`#${x.id}`}
                className="detail-toc-link"
                title={x.title}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(x.id)?.scrollIntoView({ block: 'start' });
                }}
              >
                <span className="detail-toc-index">{idx(x.id)}</span>
                <span className="detail-toc-title">{x.short}</span>
                {x.count ? <span className="detail-toc-count">{x.count}</span> : null}
              </a>
            ))}
          </nav>

          <section id="published-in" className="section detail-section">
            <SectionHead
              index={idx('published-in')}
              title="Published in"
              aside={copies.data ? <span className="soft small">{copies.data.length} {copies.data.length === 1 ? 'copy' : 'copies'}</span> : null}
            />
            {copies.isPending ? (
              <Loading label="Reading the copies" />
            ) : copies.isError ? (
              <ErrorNote error={copies.error} onRetry={() => void copies.refetch()} />
            ) : (
              <PublishedIn issueId={row.id} copies={copies.data ?? []} />
            )}
          </section>

          <section id="where-named" className="section detail-section">
            <SectionHead index={idx('where-named')} title="Where the ingredient is named" />
            {docIds.length === 0 ? (
              <p className="soft">No document is linked yet.</p>
            ) : evidence.isPending ? (
              <Loading label="Reading the original texts" />
            ) : evidence.isError ? (
              <ErrorNote error={evidence.error} onRetry={() => void evidence.refetch()} />
            ) : (
              <MatchedText
                documents={documents}
                matches={evidence.data.matches}
                texts={evidence.data.texts}
                attachments={evidence.data.attachments}
              />
            )}
          </section>

          <section id="original" className="section detail-section">
            <SectionHead
              index={idx('original')}
              title="The original document"
              aside={
                pdfs.length > 1 ? (
                  <Select
                    aria-label="Which file to show"
                    value={shownPdf?.key ?? ''}
                    onChange={(e) => setPdfKey(e.target.value)}
                    options={pdfs.map((p) => ({ value: p.key, label: p.label }))}
                  />
                ) : null
              }
            />
            {shownPdf ? (
              <PdfViewer key={shownPdf.key} r2Key={shownPdf.key} label={shownPdf.label} filename={shownPdf.filename} />
            ) : evidence.isPending && docIds.length > 0 ? (
              <Loading label="Looking for the archived files" />
            ) : (
              <p className="soft">
                No PDF is archived for this notification. The notice itself is on the regulator’s site
                {link ? (
                  <>
                    {' '}
                    (
                    <a href={link} target="_blank" rel="noopener noreferrer">
                      open it
                    </a>
                    )
                  </>
                ) : null}
                .
              </p>
            )}
          </section>

          {isLabelChange ? (
            <section id="what-changed" className="section detail-section">
              <SectionHead index={idx('what-changed')} title="What changed in the product information" />
              {spc.isPending ? (
                <Loading label="Reading the changes" />
              ) : spc.isError ? (
                <ErrorNote error={spc.error} onRetry={() => void spc.refetch()} />
              ) : (
                <SpcDiff changes={spc.data} />
              )}
            </section>
          ) : null}
        </div>

        <aside className="detail-aside">
          <CaseReport issueId={row.id} enabled={row.doc_type === 'literature'} />

          <DecisionPanel issue={row} />

          <SignalPanel issue={row} />

          <section className="panel">
            <h2 className="panel-title">Review history</h2>
            {reviews.isPending ? (
              <Loading />
            ) : reviews.isError ? (
              <ErrorNote error={reviews.error} />
            ) : (
              <ReviewHistory events={reviews.data} />
            )}
          </section>

          <section className="panel">
            <h2 className="panel-title">{isAdmin ? 'Who was notified' : 'Messages to you'}</h2>
            {notified.isPending ? (
              <Loading />
            ) : notified.isError ? (
              <ErrorNote error={notified.error} />
            ) : (
              <WhoWasNotified rows={notified.data} mine={!isAdmin} />
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
