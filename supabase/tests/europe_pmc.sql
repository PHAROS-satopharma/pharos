-- PHAROS CI — Europe PMC, the second literature source (0066). Runs on the database ci.yml prepared: CI Reader (…b2)
-- exists. Everything happens in one transaction that is rolled back at the end, so nothing is left behind.

begin;

create function pg_temp.is_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.is_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- ───────────── literature_search remembers Europe PMC's searches ─────────────
insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('europepmc', 'ci europamine', 'name', '2025-11-06', '2026-11-06');
select pg_temp.is_assert(
  pg_temp.is_refused($q$insert into literature_search (db, query, kind, look_back_from, history_until)
                        values ('scopus', 'ci europamine', 'name', '2025-11-06', '2026-11-06')$q$) like '23514 %',
  'a search is remembered for PubMed, PMC or Europe PMC, and no other database');

-- ───────────── one ingredient, two literature sources, three papers ─────────────
insert into ingredient (id, inn_en, atc_code) values ('00000000-0000-0000-0000-00000066a001', 'CI europamine', 'Z99ZZ66');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-00000066c001', '00000000-0000-0000-0000-00000066a001', 'en', 'CI europamine');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-EP-N', 'XN', 'CI Paperland', 'CI Library', '{en}', null),
  ('CI-EP-E', 'XN', 'CI Paperland', 'CI Europe Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-ep-ncbi', 'CI-EP-N', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true),
  ('ci-ep-epmc', 'CI-EP-E', 'literature', 'api', 'https://epmc.example.test/', 'europepmc', '{en}',
   'https://europepmc.example.test/', true);

-- e001: NCBI's, found again by Europe PMC. e002: Europe PMC's, a preprint. e003: Europe PMC's, in PubMed too.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-00000066e001', 'ci-ep-ncbi', '1', 'https://pubmed.ncbi.nlm.nih.gov/1/',
   'CI europamine and the liver', 'en', 'literature', '2026-11-02', '2026-11-03 08:00+00', false,
   '{"pmid":"1","pubmed_url":"https://pubmed.ncbi.nlm.nih.gov/1/","journal":"CI Journal",'
   '"found_in":["europepmc","pubmed"],"queries":[{"query":"CI europamine","kind":"name","db":["europepmc","pubmed"]}],'
   '"class_only":false,"look_back":false}'),
  ('00000000-0000-0000-0000-00000066e002', 'ci-ep-epmc', 'PPR2', 'https://europepmc.org/article/PPR/PPR2',
   'CI europamine in rats', 'en', 'literature', '2026-11-04', '2026-11-04 08:00+00', false,
   '{"pmid":null,"pmcid":null,"europepmc_id":"PPR2","europepmc_url":"https://europepmc.org/article/PPR/PPR2",'
   '"preprint":true,"journal":"CI Preprints","found_in":["europepmc"],'
   '"queries":[{"query":"CI europamine","kind":"name","db":["europepmc"]}],"class_only":false,"look_back":false}'),
  ('00000000-0000-0000-0000-00000066e003', 'ci-ep-epmc', '3', 'https://europepmc.org/article/MED/3',
   'A cohort mentioning CI europamine in its methods', 'en', 'literature', '2026-11-05', '2026-11-05 08:00+00', false,
   '{"pmid":"3","pubmed_url":"https://pubmed.ncbi.nlm.nih.gov/3/","europepmc_id":"3",'
   '"europepmc_url":"javascript:alert(1)","preprint":false,"found_in":["europepmc"],'
   '"queries":[{"query":"CI europamine","kind":"name","db":["europepmc"]}],"class_only":false,"look_back":true}');
insert into match (document_id, ingredient_id, term_id, field, matched_text)
  select d, '00000000-0000-0000-0000-00000066a001', '00000000-0000-0000-0000-00000066c001', 'structured', 'CI europamine'
    from unnest(array['00000000-0000-0000-0000-00000066e001', '00000000-0000-0000-0000-00000066e002',
                      '00000000-0000-0000-0000-00000066e003']::uuid[]) as d;

-- ───────────── the screen, as a reader ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select ingredient_screen('00000000-0000-0000-0000-00000066a001', '2026-11-01', '2026-11-07') -> 'literature'
       as lit \gset
select string_agg(right(document_id::text, 4) || '|' || coalesce(pubmed_url, '-') || '|'
                  || coalesce(europepmc_url, '-') || '|' || preprint || '|' || is_backfill, ' ' order by document_id)
         as papers
  from ingredient_papers('00000000-0000-0000-0000-00000066a001', '2026-11-01', '2026-11-07') \gset
reset role;

select pg_temp.is_assert((:'lit'::jsonb ->> 'papers')::int = 3
                         and (:'lit'::jsonb ->> 'pubmed')::int = 1
                         and (:'lit'::jsonb ->> 'pmc')::int = 0
                         and (:'lit'::jsonb ->> 'europepmc')::int = 3
                         and (:'lit'::jsonb ->> 'preprints')::int = 1,
  'the papers counted by database, Europe PMC beside PubMed and PMC, and the preprints apart');
select pg_temp.is_assert(:'lit'::jsonb -> 'by_query'
                         = '[{"query":"ci europamine","kind":"name","pubmed":1,"pmc":0,"europepmc":3}]'::jsonb,
  'each search counts what Europe PMC found');
select pg_temp.is_assert(
  (select string_agg((p ->> 'preprint') || '|' || coalesce(p ->> 'europepmc_url', '-'), ' '
                     order by p ->> 'document_id')
     from jsonb_array_elements(:'lit'::jsonb -> 'first') p)
  = 'false|- true|https://europepmc.org/article/PPR/PPR2 false|-',
  'the first papers carry the preprint flag and their Europe PMC page');
select pg_temp.is_assert(:'papers' =
    'e001|https://pubmed.ncbi.nlm.nih.gov/1/|-|false|false '
    || 'e002|-|https://europepmc.org/article/PPR/PPR2|true|false '
    || 'e003|https://pubmed.ncbi.nlm.nih.gov/3/|-|false|true',
  'every paper with its links (a page that is not https is never a link), the preprint and the look-back flags');

rollback;
