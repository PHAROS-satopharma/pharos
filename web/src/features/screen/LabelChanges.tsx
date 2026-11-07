import { useMutation, useQueryClient } from '@tanstack/react-query';
import { errorMessage, unwrap } from '../../lib/api';
import { useAuth } from '../../lib/auth';
import { formatDate, formatDateTime } from '../../lib/format';
import { languageName } from '../../lib/labels';
import { safeHref } from '../../lib/safeHref';
import { supabase } from '../../lib/supabase';
import { Button } from '../../ui/Button';
import { Country } from '../../ui/Flag';
import { ErrorNote, Loading, Notice } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';
import { cx } from '../../ui/cx';
import { DecisionButtons } from './DecisionButtons';
import { OurLabel } from './OurLabel';
import { LabelWatch } from './LabelWatch';
import { labelChangesKey, useLabelChanges } from './queries';
import type { DiffSection, Findings, GapSection, GapStatus, LabelChange, Mention } from './types';
import '../../styles/labels.css';

const STATUS: Record<GapStatus, { label: string; tone: 'success' | 'warning' | 'danger'; title: string }> = {
  covered: {
    label: 'Our label says this',
    tone: 'success',
    title: 'Three quarters or more of its words are in one sentence of ours.',
  },
  partly: { label: 'Partly in our label', tone: 'warning', title: 'Some of its words are in one sentence of ours. Read both.' },
  missing: { label: 'Not in our label', tone: 'danger', title: 'Few or none of its words are in this section of ours.' },
};

/**
 * Section 03 of the Ingredients screen: the label changes of products with the ingredient DETECTED in the days
 * chosen (label_changes, 0043), the reference product first, then newest first; above them our own label. Each
 * change shows what the collector found against our label: every sentence the originator added, tagged as said,
 * partly said or not said by our label; the word changes; the notice and its decision. Between our label and the
 * changes, what the label watch read per database page (LabelWatch).
 */
export function LabelChanges({ ingredientId, from, to }: { ingredientId: string; from: string; to: string }) {
  const q = useLabelChanges(ingredientId, from, to);
  const key = labelChangesKey(ingredientId, from, to);
  const changes = q.data?.changes ?? [];
  const mentions = new Map((q.data?.label_changes ?? []).map((m) => [m.document_id, m]));
  const findings = q.data?.findings ?? {};
  return (
    <section className="scr-section" aria-label="Label changes">
      <SectionHead index="03" title="Label changes" aside={q.data ? `${changes.length}` : undefined} />
      <OurLabel ingredientId={ingredientId} />
      <LabelWatch ingredientId={ingredientId} />
      {q.isPending ? (
        <Loading label="Reading the label changes" />
      ) : q.isError ? (
        <ErrorNote title="The label changes could not be read." error={q.error} onRetry={() => void q.refetch()} />
      ) : changes.length ? (
        <ol className="scr-mentions">
          {changes.map((c) => (
            <ChangeItem key={c.change_id} c={c} mention={mentions.get(c.change_id)} findings={findings} queryKey={key} />
          ))}
        </ol>
      ) : (
        <p className="scr-quiet">No label change of a product with this ingredient was detected in these days.</p>
      )}
    </section>
  );
}

/** One change; its notice's clock comes from the section's own data (`findings`), as on the screen's mentions. */
function ChangeItem({
  c,
  mention,
  findings,
  queryKey,
}: {
  c: LabelChange;
  mention: Mention | undefined;
  findings: Findings;
  queryKey: readonly unknown[];
}) {
  const { canReview } = useAuth();
  const qc = useQueryClient();
  const mark = useMutation({
    mutationFn: async (on: boolean) => {
      unwrap(await supabase.rpc('set_reference_product', { p_product: c.product.id, p_on: on }));
    },
    onSuccess: async () => {
      // One reference per ingredient: the other product may have lost the mark, so the whole list is read again.
      await qc.invalidateQueries({ queryKey: ['label-changes'] });
    },
  });
  const href = safeHref(c.link);
  const gaps = new Map((c.gap?.sections ?? []).map((g) => [g.section, g]));
  const sections = Array.isArray(c.diff) ? c.diff.filter((d) => d && typeof d.section === 'string') : [];

  return (
    <li className={cx('scr-mention', 'lab-change', c.is_backfill && 'is-history', c.product.is_reference && 'is-reference')}>
      <div className="scr-meta">
        <span className="scr-date" title={`Detected ${formatDateTime(c.detected_at)}`}>
          Detected {formatDate(c.detected_day)}
        </span>
        {c.label_date ? (
          <span>
            Label dated {formatDate(c.label_date)}
            {c.previous_label_date ? ` (before: ${formatDate(c.previous_label_date)})` : ''}
          </span>
        ) : null}
        <Country name={c.product.country_name} code={c.product.country_code} />
        <span>{c.product.regulator_name}</span>
        {c.product.is_reference ? (
          <Tag tone="neutral" title="The product whose label is followed first for this ingredient">
            Reference product
          </Tag>
        ) : null}
        {c.is_backfill ? (
          <Tag tone="quiet" title="Found by a look into the past; it was never alerted">
            History
          </Tag>
        ) : null}
      </div>
      <p className="scr-title" lang={c.lang ?? undefined}>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {c.product.name}
          </a>
        ) : (
          c.product.name
        )}
        {c.product.mah ? <span className="lab-mah"> · {c.product.mah}</span> : null}
      </p>
      {c.sections.length ? <p className="scr-sections">Sections changed: {c.sections.join(', ')}</p> : null}

      <GapLine c={c} />
      {sections.length ? (
        <div className="lab-sections">
          {sections.map((d) => (
            <SectionDetails key={d.section} d={d} g={gaps.get(d.section)} lang={c.lang} />
          ))}
        </div>
      ) : null}

      {canReview ? (
        <div className="lab-actions">
          <Button size="sm" variant="quiet" busy={mark.isPending} onClick={() => mark.mutate(!c.product.is_reference)}>
            {c.product.is_reference ? 'Not the reference product' : 'Mark as the reference product'}
          </Button>
        </div>
      ) : null}
      {mark.isError ? <Notice tone="error">Not changed: {errorMessage(mark.error)}</Notice> : null}

      {mention ? (
        <DecisionButtons
          mention={mention}
          queryKey={queryKey}
          finding={mention.issue_id ? (findings[mention.issue_id] ?? null) : null}
        />
      ) : null}
    </li>
  );
}

/** One line on the gap between this change and our label, as the weekly report words it. */
function GapLine({ c }: { c: LabelChange }) {
  if (!c.our_label) {
    return <p className="lab-gap-quiet">No label of ours uploaded yet: upload it above and this change is compared with it.</p>;
  }
  const ours = `${c.our_label.product_name}, ${c.our_label.version}`;
  if (!c.gap) {
    return (
      <p className="lab-gap-quiet">
        Not compared with our label ({ours}) yet: within 4 hours of the upload, on the next collection run.
      </p>
    );
  }
  if (!c.gap.lang_match) {
    return (
      <p className="lab-gap-quiet">
        Our label ({ours}) is in {languageName(c.gap.our_lang)} and this one in {languageName(c.gap.their_lang)}: labels
        are never compared across languages, so compare them by eye.
      </p>
    );
  }
  const g = c.gap;
  const added = g.covered + g.partly + g.missing;
  return (
    <p className="lab-gap">
      <span>
        Our label ({ours}): {g.covered} covered, {g.partly} partly, {g.missing} missing
      </span>
      {added > 0 && g.missing > 0 ? (
        <Tag tone="danger">
          {g.missing} of {added} added {added === 1 ? 'sentence' : 'sentences'} not in our label
        </Tag>
      ) : added > 0 && g.partly === 0 ? (
        <Tag tone="success">Every added sentence is in our label</Tag>
      ) : null}
      {c.gap_at ? <span className="muted">Compared {formatDateTime(c.gap_at)}</span> : null}
    </p>
  );
}

/** One changed section, folded: the added sentences against ours, then the word changes in their text. */
function SectionDetails({ d, g, lang }: { d: DiffSection; g: GapSection | undefined; lang: string | null }) {
  const words = Array.isArray(d.changes) ? d.changes : [];
  return (
    <details className="lab-section">
      <summary>
        <span className="lab-section-name">Section {d.section}</span>
        <span className="lab-section-counts">
          {g
            ? g.added.length
              ? `${g.added.length} added · ${g.covered} covered, ${g.partly} partly, ${g.missing} missing`
              : 'Nothing added'
            : `${words.length} word ${words.length === 1 ? 'change' : 'changes'}`}
        </span>
      </summary>
      {g ? (
        g.added.length ? (
          <>
            {!g.our_text ? (
              <p className="lab-gap-quiet">
                Our label has no section {g.our_section}, so every added sentence counts as not in our label.
              </p>
            ) : null}
            <ol className="lab-added">
              {g.added.map((a, i) => (
                <li key={i} className={cx('lab-added-item', `lab-added-${a.status}`)}>
                  <Tag tone={STATUS[a.status].tone} title={STATUS[a.status].title}>
                    {STATUS[a.status].label}
                  </Tag>
                  <p className="lab-theirs" dir="auto" lang={lang ?? undefined}>
                    {a.sentence}
                  </p>
                  {a.closest && a.status !== 'missing' ? (
                    <p className="lab-ours-says" dir="auto">
                      Ours: {a.closest}
                    </p>
                  ) : null}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="lab-gap-quiet">The originator removed or reworded text here but added no new sentence.</p>
        )
      ) : null}
      {words.length ? (
        <div className="lab-diff">
          <span className="lab-diff-head">Word changes in their text</span>
          <div className="diff-text" dir="auto" lang={lang ?? undefined}>
            {words.map((w, i) => (
              <span key={i}>
                {w.context ? <span className="lab-ctx">{w.context} </span> : null}
                {w.before ? <del className="diff-del">{w.before}</del> : null}
                {w.before && w.after ? ' ' : ''}
                {w.after ? <ins className="diff-ins">{w.after}</ins> : null}{' '}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </details>
  );
}
