// The answer of the literature-search Edge Function (supabase/functions/literature-search).

export type LiteratureDb = 'pubmed' | 'pmc';

/** One database's live count, and the link that opens the very same search on its website. */
export interface LiteratureCount {
  count: number | null; // null: the database did not answer (error says so)
  url: string;
  error?: string;
}

/** One search: the ingredient's English name, or one English word of its drug class. */
export interface LiteratureQuery {
  label: string;
  kind: 'name' | 'class';
  pubmed: LiteratureCount;
  pmc: LiteratureCount;
}

export interface LiteratureSearchResult {
  ingredient: { id: string; inn_en: string };
  from: string; // YYYY-MM-DD, publication dates, both days included
  to: string;
  checked_at: string; // when NCBI was asked (UTC)
  queries: LiteratureQuery[];
  note?: string;
}
