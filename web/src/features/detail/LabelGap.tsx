import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { addedSentences, compareWithOurs, euSection, sameLanguage, type GapStatus } from '../../lib/labelGap';
import { languageName } from '../../lib/labels';
import { Tag } from '../../ui/Tag';
import type { OurLabel } from '../labels/queries';
import type { SpcDiffSection } from './queries';

export type CurrentLabel = Pick<OurLabel, 'id' | 'ingredient_id' | 'product_name' | 'version' | 'lang' | 'sections'>;

const STATUS: Record<GapStatus, { label: string; tone: 'success' | 'warning' | 'danger'; title: string }> = {
  covered: { label: 'Our label says this', tone: 'success', title: 'Three quarters or more of its words are in one sentence of ours.' },
  partly: { label: 'Partly in our label', tone: 'warning', title: 'Some of its words are in one sentence of ours. Read both.' },
  missing: { label: 'Not in our label', tone: 'danger', title: 'Few or none of its words are in this section of ours.' },
};

/** Under one changed section: what the originator added, set against the same section of each of our labels. */
export function LabelGap({ section, ours, langs }: { section: SpcDiffSection; ours: CurrentLabel[]; langs: string[] }) {
  const target = euSection(section.section);
  const added = useMemo(() => addedSentences(section.before, section.after), [section.before, section.after]);
  if (!target) return null;
  if (ours.length === 0) {
    return (
      <p className="label-gap soft small">
        No label of ours is saved for this ingredient, so this change cannot be checked against it.{' '}
        <Link to="/labels">Add our label</Link>
      </p>
    );
  }
  return (
    <div className="label-gap">
      {ours.map((label) => (
        <OneLabel key={label.id} label={label} target={target} added={added} langs={langs} />
      ))}
    </div>
  );
}

function OneLabel({ label, target, added, langs }: { label: CurrentLabel; target: string; added: string[]; langs: string[] }) {
  const [showOurs, setShowOurs] = useState(false);
  const ourText = label.sections[target] ?? '';
  const comparable = langs.some((l) => sameLanguage(l, label.lang));
  const results = useMemo(() => (comparable ? compareWithOurs(added, ourText) : []), [comparable, added, ourText]);
  const missing = results.filter((r) => r.status === 'missing').length;

  return (
    <div className="label-gap-one">
      <div className="label-gap-head">
        <span className="micro">
          Our label · {label.product_name} · section {target}
        </span>
        <span className="soft small" dir="auto">
          {label.version}
        </span>
        {comparable && added.length > 0 ? (
          missing > 0 ? (
            <Tag tone="danger">
              {missing} of {added.length} added {added.length === 1 ? 'sentence' : 'sentences'} not in our label
            </Tag>
          ) : (
            <Tag tone="success">Every added sentence is in our label</Tag>
          )
        ) : null}
      </div>
      {!ourText ? (
        <p className="soft small">Our label has no section {target}.</p>
      ) : !comparable ? (
        <p className="soft small">
          Our label is in {languageName(label.lang)} and this product information is not, so compare them by eye.
        </p>
      ) : added.length === 0 ? (
        <p className="soft small">The originator removed or reworded text here but added no new sentence.</p>
      ) : (
        <ol className="label-gap-list">
          {results.map((r, i) => (
            <li key={i} className={`label-gap-item label-gap-${r.status}`}>
              <div className="label-gap-line">
                <Tag tone={STATUS[r.status].tone} title={STATUS[r.status].title}>
                  {STATUS[r.status].label}
                </Tag>
              </div>
              <p className="label-gap-theirs" dir="auto">
                {r.sentence}
              </p>
              {r.closest && r.status !== 'missing' ? (
                <p className="label-gap-ours soft small" dir="auto">
                  Ours: {r.closest}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      )}
      {ourText ? (
        <>
          <button type="button" className="link-button small" onClick={() => setShowOurs((v) => !v)}>
            {showOurs ? 'Hide' : 'Show'} our section {target}
          </button>
          {showOurs ? (
            <div className="diff-text label-gap-full" dir="auto">
              {ourText}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
