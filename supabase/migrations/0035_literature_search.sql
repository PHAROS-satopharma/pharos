-- PHAROS — the NCBI literature searches the collector has run (2026-11-06).
--
-- The literature watch (collectors/parsers/pubmed.py) searches PubMed and PubMed Central every day for each
-- active ingredient's English name and each English word of its drug classes. A search never run before (a
-- newly added ingredient or class word) first looks back 12 months of entry dates and stores what it finds as
-- history (no alert); after that it reads only what was entered since the last complete run. This table is how
-- the collector knows which searches it has run: one row per database and search words (lower case, as NCBI
-- ignores case), with the look-back's first and last day and when every paper it found was stored. A look-back
-- cut short by the run's item cap or time budget stays unfinished (look_back_done_at null) and continues on the
-- next run. A search not run for 90 days (its ingredient was switched off) looks back again.
--
-- Only the collector writes it (the database owner, through SUPABASE_DB_URL); a team member can read it.

create table literature_search (
  db                 text not null check (db in ('pubmed', 'pmc')),
  query              text not null check (query <> '' and query = lower(query)),
  kind               text not null check (kind in ('name', 'class')),
  look_back_from     date not null,
  history_until      date not null,
  look_back_done_at  timestamptz,
  last_searched_at   timestamptz not null default now(),
  created_at         timestamptz not null default now(),
  primary key (db, query),
  check (look_back_from <= history_until)
);
comment on table literature_search is
  'NCBI searches run by the literature collector: the 12-month look-back of each new search word, and whether it finished.';

alter table literature_search enable row level security;
create policy literature_search_read on literature_search for select to authenticated using (my_role() is not null);
revoke all on literature_search from anon;
revoke insert, update, delete, truncate on literature_search from authenticated;
grant select on literature_search to authenticated;
