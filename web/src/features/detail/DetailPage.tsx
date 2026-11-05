import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useCopies, useEvidence, useIssue, useNotified, useReviews, useSpcChanges, type CopyDocument } from './queries';
import { DecisionPanel } from './DecisionPanel';
import { PublishedIn } from './PublishedIn';
import { MatchedText } from './MatchedText';
import { PdfViewer } from './PdfViewer';
import { SpcDiff } from './SpcDiff';
import { ReviewHistory, WhoWasNotified } from './History';
import { formatDate } from '../../lib/format';
import { DOC_TYPE_LABEL } from '../../lib/labels';
import { Country } from '../../ui/Flag';
import { Select } from '../../ui/Select';
import { Empty, ErrorNote, Loading } from '../../ui/States';
import { StatusPill, Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';

interface PdfFile {
  key: string;
  label: string;
}

function isPdf(mime: string | null | undefined, name: string | null | undefined): boolean {
  return (mime ?? '').toLowerCase().includes('pdf') || (name ?? '').toLowerCase().endsWith('.pdf');
}

export function DetailPage() {
  const { id = '' } = useParams();
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
  const [pdfKey, setPdfKey] = useState<string>('');

  const pdfs = useMemo<PdfFile[]>(() => {
    const out: PdfFile[] = [];
    for (const d of documents) {
      const where = d.source?.regulator?.name ?? 'Regulator';
      if (d.r2_key && isPdf(d.mime, d.url)) out.push({ key: d.r2_key, label: `${where}: the notice` });
      for (const a of evidence.data?.attachments ?? []) {
        if (a.document_id === d.id && a.r2_key && isPdf(a.mime, a.filename ?? a.url)) {
          out.push({ key: a.r2_key, label: `${where}: ${a.filename ?? 'attached file'}` });
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
      <Empty title="This notification does not exist." action={<Link to="/">Back to the notifications</Link>}>
        <p>It may have been merged into another notification, or the link is incomplete.</p>
      </Empty>
    );
  }

  const anchor = documents.find((d) => (copies.data ?? []).some((c) => c.link === 'anchor' && c.document?.id === d.id));
  const shownPdf = pdfs.find((p) => p.key === pdfKey) ?? pdfs[0] ?? null;
  const isLabelChange = row.doc_type === 'label_change' || (spc.data?.length ?? 0) > 0;
  let n = 0;
  const idx = () => String(++n).padStart(2, '0');

  return (
    <div className="page detail">
      <header className="detail-head masthead">
        <Link to="/" className="back-link">
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
        <div className="detail-meta">
          <StatusPill status={row.status} />
          <Country name={row.anchor_country} />
          <span>{row.anchor_regulator}</span>
          {(row.ingredients ?? []).length > 0 ? <span>· {(row.ingredients ?? []).join(', ')}</span> : null}
          {row.link ? (
            <a href={row.link} target="_blank" rel="noopener noreferrer" className="ext-link">
              Open on the regulator’s site <span aria-hidden>↗</span>
            </a>
          ) : null}
        </div>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="section">
            <SectionHead
              index={idx()}
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

          <section className="section">
            <SectionHead index={idx()} title="Where the ingredient is named" />
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

          <section className="section">
            <SectionHead
              index={idx()}
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
              <PdfViewer key={shownPdf.key} r2Key={shownPdf.key} label={shownPdf.label} />
            ) : evidence.isPending && docIds.length > 0 ? (
              <Loading label="Looking for the archived files" />
            ) : (
              <p className="soft">
                No PDF is archived for this notification. The notice itself is on the regulator’s site
                {row.link ? (
                  <>
                    {' '}
                    (
                    <a href={row.link} target="_blank" rel="noopener noreferrer">
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
            <section className="section">
              <SectionHead index={idx()} title="What changed in the product information" />
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
          <DecisionPanel issue={row} />

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
            <h2 className="panel-title">Who was notified</h2>
            {notified.isPending ? (
              <Loading />
            ) : notified.isError ? (
              <ErrorNote error={notified.error} />
            ) : (
              <WhoWasNotified rows={notified.data} />
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
