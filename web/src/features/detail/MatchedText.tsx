import { useMemo, useState, type ReactNode } from 'react';
import { excerpts, findOccurrences, resolveRanges, segments, type Segment } from '../../lib/highlight';
import { FIELD_LABEL, languageName } from '../../lib/labels';
import type { AttachmentRow, DocumentTextRow, MatchRow } from '../../lib/types';
import type { CopyDocument } from './queries';
import { Country } from '../../ui/Flag';
import { Tag } from '../../ui/Tag';

function Marked({ segs }: { segs: Segment[] }) {
  return (
    <>
      {segs.map((s) =>
        s.mark ? (
          <mark key={s.start} className="hl">
            {s.text}
          </mark>
        ) : (
          <span key={s.start}>{s.text}</span>
        ),
      )}
    </>
  );
}

function whatMatched(ms: MatchRow[]): string[] {
  const names = new Set<string>();
  for (const m of ms) {
    if (m.ingredient) names.add(m.ingredient.inn_en);
    else if (m.drug_class) names.add(`${m.drug_class.name_en} (class-wide)`);
  }
  return [...names];
}

function TextBlock({
  label,
  text,
  ms,
  lang,
}: {
  label: ReactNode;
  text: string | null;
  ms: MatchRow[];
  lang: string | null;
}) {
  const [full, setFull] = useState(false);
  const ranges = useMemo(
    () => (text ? resolveRanges(text, ms.map((m) => ({ start: m.start_offset, end: m.end_offset, text: m.matched_text }))) : []),
    [text, ms],
  );
  const possible = ms.some((m) => m.confidence === 'possible');

  // No stored text: show the snippets the matcher kept, with the words marked in each.
  if (!text || ranges.length === 0) {
    const snippets = ms.filter((m) => m.snippet || m.matched_text);
    return (
      <div className="evidence-block">
        <div className="evidence-label">
          {label}
          {possible ? <Tag tone="warning">Possible match, check the original</Tag> : null}
        </div>
        {snippets.map((m) => {
          const s = m.snippet ?? m.matched_text;
          const segs = segments(s, findOccurrences(s, m.matched_text));
          return (
            <p key={m.id} className="excerpt" dir="auto" lang={lang ?? undefined}>
              <Marked segs={segs} />
            </p>
          );
        })}
      </div>
    );
  }

  const parts = excerpts(text, ranges, 180);
  return (
    <div className="evidence-block">
      <div className="evidence-label">
        {label}
        <span className="evidence-count">
          {ranges.length} {ranges.length === 1 ? 'place' : 'places'}
        </span>
        {possible ? <Tag tone="warning">Possible match, check the original</Tag> : null}
      </div>
      {full ? (
        <div className="fulltext" dir="auto" lang={lang ?? undefined}>
          <Marked segs={segments(text, ranges)} />
        </div>
      ) : (
        parts.map((p) => (
          <p key={p.start} className="excerpt" dir="auto" lang={lang ?? undefined}>
            {p.clippedStart ? <span className="ellipsis">… </span> : null}
            <Marked segs={p.segments} />
            {p.clippedEnd ? <span className="ellipsis"> …</span> : null}
          </p>
        ))
      )}
      <button type="button" className="link-button small" onClick={() => setFull((v) => !v)}>
        {full ? 'Show only the passages that matched' : 'Show the whole text'}
      </button>
    </div>
  );
}

export function MatchedText({
  documents,
  matches,
  texts,
  attachments,
}: {
  documents: CopyDocument[];
  matches: MatchRow[];
  texts: DocumentTextRow[];
  attachments: AttachmentRow[];
}) {
  const withMatches = documents.filter((d) => matches.some((m) => m.document_id === d.id));
  if (withMatches.length === 0) {
    return <p className="soft">No matched words are stored for this notification.</p>;
  }
  return (
    <div className="evidence">
      {withMatches.map((d) => {
        const ms = matches.filter((m) => m.document_id === d.id);
        const titleMs = ms.filter((m) => m.field === 'title');
        const bodyMs = ms.filter((m) => (m.field === 'body' || m.field === 'attachment') && !m.attachment_id);
        const structuredMs = ms.filter((m) => m.field === 'structured');
        const attIds = [...new Set(ms.filter((m) => m.attachment_id).map((m) => m.attachment_id as string))];
        const bodyText = texts.find((t) => t.document_id === d.id && !t.attachment_id)?.text ?? null;
        const reg = d.source?.regulator ?? null;
        const titleRanges = resolveRanges(
          d.title_orig,
          titleMs.map((m) => ({ start: m.start_offset, end: m.end_offset, text: m.matched_text })),
        );
        return (
          <article key={d.id} className="evidence-doc">
            <header className="evidence-head">
              <span className="evidence-where">
                <Country name={reg?.country_name ?? null} code={reg?.country_code ?? null} />
                <span className="evidence-regulator">{reg?.name}</span>
                <span className="evidence-lang">{languageName(d.lang)}</span>
              </span>
              <span className="evidence-matched">
                <span className="micro soft">Matched</span>
                <span className="chips">
                  {whatMatched(ms).map((name) => (
                    <span key={name} className="chip">
                      {name}
                    </span>
                  ))}
                </span>
              </span>
            </header>
            <h3 className="evidence-title" dir="auto" lang={d.lang ?? undefined}>
              <Marked segs={segments(d.title_orig, titleRanges)} />
            </h3>
            {structuredMs.length > 0 ? (
              <p className="small">
                <span className="micro soft">{FIELD_LABEL.structured}</span>{' '}
                {structuredMs.map((m) => (
                  <span key={m.id}>
                    <mark className="hl" dir="auto">
                      {m.matched_text}
                    </mark>{' '}
                  </span>
                ))}
              </p>
            ) : null}
            {bodyMs.length > 0 ? (
              <TextBlock label={<span className="micro soft">{FIELD_LABEL.body}</span>} text={bodyText} ms={bodyMs} lang={d.lang} />
            ) : null}
            {attIds.map((aid) => {
              const att = attachments.find((a) => a.id === aid);
              const attText = texts.find((t) => t.document_id === d.id && t.attachment_id === aid)?.text ?? null;
              return (
                <TextBlock
                  key={aid}
                  label={
                    <span className="micro soft">
                      {FIELD_LABEL.attachment}: {att?.filename ?? 'file'}
                      {att?.extraction === 'ocr' ? ' (read by OCR)' : ''}
                    </span>
                  }
                  text={attText}
                  ms={ms.filter((m) => m.attachment_id === aid)}
                  lang={d.lang}
                />
              );
            })}
          </article>
        );
      })}
    </div>
  );
}
