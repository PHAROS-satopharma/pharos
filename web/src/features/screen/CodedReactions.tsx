import { useQuery } from '@tanstack/react-query';
import { unwrap } from '../../lib/api';
import { formatDateTime } from '../../lib/format';
import { supabase } from '../../lib/supabase';
import { ErrorNote, Loading } from '../../ui/States';
import { Tag } from '../../ui/Tag';
import { SectionHead } from '../../ui/Text';

type Listed = 'our_label' | 'reference' | null;

interface TermCount {
  ui: string;
  name: string;
  categories: string[] | null;
  cases_now: number;
  cases_before: number;
  papers_now: number;
  papers_before: number;
  listed: Listed;
}

interface TopicCount {
  topic: string;
  name: string;
  cases_now: number;
  cases_before: number;
  papers_now: number;
  papers_before: number;
  terms: string[];
}

interface LabelCoded {
  source: 'our_label' | 'reference';
  label_name: string;
  terms: number;
  coded_at: string;
}

interface Coded {
  terms: TermCount[];
  topics: TopicCount[];
  labels: LabelCoded[];
}

function useCoded(ingredientId: string, from: string, to: string) {
  return useQuery({
    queryKey: ['coded-reactions', ingredientId, from, to] as const,
    enabled: Boolean(ingredientId),
    staleTime: 5 * 60_000,
    queryFn: async (): Promise<Coded> => {
      const args = { p_ingredient: ingredientId, p_from: from, p_to: to };
      const [terms, topics, labels] = await Promise.all([
        supabase.rpc('ingredient_mesh_counts', args),
        supabase.rpc('ingredient_topic_counts', args),
        supabase.from('label_coded').select('source, label_name, terms, coded_at').eq('ingredient_id', ingredientId),
      ]);
      return {
        terms: unwrap<TermCount[] | null>(terms) ?? [],
        topics: unwrap<TopicCount[] | null>(topics) ?? [],
        labels: unwrap<LabelCoded[] | null>(labels) ?? [],
      };
    },
  });
}

const LISTED: Record<Exclude<Listed, null>, { label: string; tone: 'success' | 'blue'; title: string }> = {
  our_label: { label: 'In our label', tone: 'success', title: 'Section 4.8 of our label names it, or a broader heading above it.' },
  reference: {
    label: 'In the reference label',
    tone: 'blue',
    title: 'Not found in our label; the reference product’s adverse reactions name it, or a broader heading above it.',
  },
};

/** "3 (1 before)": the days chosen, then the same number of days just before them. */
function Count({ now, before }: { now: number; before: number }) {
  if (!now && !before) return <span className="scr-quiet">–</span>;
  return (
    <>
      <strong>{now}</strong> <span className="scr-quiet">({before} before)</span>
    </>
  );
}

/**
 * Section 05 of the Ingredients screen: what the coded terms say (ingredient_mesh_counts and ingredient_topic_counts,
 * 0062). The cases' reactions as the reviewers coded them, and the papers NLM indexed with the reaction "chemically
 * induced", counted for the days chosen and the same number of days before; the safety topics they fall in; and
 * whether our label (or else the reference product's) lists each reaction. Counting is not judging: the team decides.
 */
export function CodedReactions({ ingredientId, from, to }: { ingredientId: string; from: string; to: string }) {
  const q = useCoded(ingredientId, from, to);
  const terms = q.data?.terms ?? [];
  const topics = q.data?.topics ?? [];
  const labels = q.data?.labels ?? [];
  const anyLabel = labels.length > 0;
  return (
    <section className="scr-section" aria-label="Reactions by MeSH">
      <SectionHead index="05" title="Reactions by MeSH" aside={q.data ? `${terms.length}` : undefined} />
      {q.isPending ? (
        <Loading label="Counting the coded reactions" />
      ) : q.isError ? (
        <ErrorNote title="The coded reactions could not be counted." error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <>
          <p className="scr-quiet">
            {anyLabel
              ? `Checked against ${[...labels]
                  .sort((a, b) => (a.source === 'our_label' ? -1 : b.source === 'our_label' ? 1 : 0))
                  .map((l) => `${l.source === 'our_label' ? 'our label' : 'the reference label'} (${l.label_name}, ` +
                    `${l.terms} terms, read ${formatDateTime(l.coded_at)})`)
                  .join(' and ')}.`
              : 'No label in English is coded yet, so the list does not say which reactions are in the label.'}
          </p>
          {topics.length ? (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">Safety topics</caption>
                <thead>
                  <tr>
                    <th>Safety topic</th>
                    <th className="num">Cases</th>
                    <th className="num">Papers</th>
                    <th>Terms found</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.map((t) => (
                    <tr key={t.topic}>
                      <td>{t.name}</td>
                      <td className="num">
                        <Count now={t.cases_now} before={t.cases_before} />
                      </td>
                      <td className="num">
                        <Count now={t.papers_now} before={t.papers_before} />
                      </td>
                      <td>{t.terms.join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {terms.length ? (
            <div className="table-wrap">
              <table className="table">
                <caption className="visually-hidden">Reactions</caption>
                <thead>
                  <tr>
                    <th>Reaction</th>
                    <th className="num">Cases</th>
                    <th className="num">Papers</th>
                    <th>Label</th>
                  </tr>
                </thead>
                <tbody>
                  {terms.map((t) => (
                    <tr key={t.ui}>
                      <td>
                        {t.name}
                        {t.categories?.length ? <div className="scr-quiet">{t.categories.join(' · ')}</div> : null}
                      </td>
                      <td className="num">
                        <Count now={t.cases_now} before={t.cases_before} />
                      </td>
                      <td className="num">
                        <Count now={t.papers_now} before={t.papers_before} />
                      </td>
                      <td>
                        {t.listed ? (
                          <Tag tone={LISTED[t.listed].tone} title={LISTED[t.listed].title}>
                            {LISTED[t.listed].label}
                          </Tag>
                        ) : anyLabel ? (
                          <Tag tone="danger" title="Neither our label nor the reference label names it or a broader heading.">
                            Not in our label
                          </Tag>
                        ) : (
                          <span className="scr-quiet">–</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="scr-quiet">
              No coded reaction in these days or the days before: no case coded, and no paper indexed by NLM with a
              reaction to the ingredient.
            </p>
          )}
          <p className="scr-quiet">
            Cases count the reactions as the reviewers coded them; papers count the headings NLM’s indexers marked
            “chemically induced”. The number in brackets is the same number of days just before. Coded with MeSH from
            the U.S. National Library of Medicine, which does not endorse PHAROS.
          </p>
        </>
      )}
    </section>
  );
}
