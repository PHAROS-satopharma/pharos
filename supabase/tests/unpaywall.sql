-- PHAROS CI — the free full text of a paper on the Ingredients screen (0068): paper_state() returns open_access.
-- Runs on the database ci.yml prepared: CI Admin (…a1) and CI Reader (…b2) exist. Everything is rolled back.

begin;

create function pg_temp.oa_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-OA-N', 'XN', 'CI Paperland', 'CI Open Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-oa-lit', 'CI-OA-N', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true);

-- open (a repository's accepted copy, CC BY); closed; open but its address is not http(s); never asked
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, first_seen_at, structured) values
  ('00000000-0000-0000-0000-00000068b001', 'ci-oa-lit', 'oa1', 'https://pubmed.ncbi.nlm.nih.gov/1/', 'Open paper',
   'en', 'literature', '2026-11-05 08:00+00',
   '{"pmid":"1","doi":"10.1000/oa1","oa":{"is_oa":true,"known":true,"url":"https://europepmc.org/articles/PMC1",
     "pdf_url":"https://europepmc.org/articles/PMC1?pdf=render","license":"cc-by","version":"accepted",
     "host_type":"repository","pdfs":[],"checked":"2026-11-06T02:40:00+00:00"}}'),
  ('00000000-0000-0000-0000-00000068b002', 'ci-oa-lit', 'oa2', 'https://pubmed.ncbi.nlm.nih.gov/2/', 'Closed paper',
   'en', 'literature', '2026-11-05 08:00+00',
   '{"pmid":"2","doi":"10.1000/oa2","oa":{"is_oa":false,"known":true,"oa_status":"closed",
     "checked":"2026-11-06T02:40:00+00:00"}}'),
  ('00000000-0000-0000-0000-00000068b003', 'ci-oa-lit', 'oa3', 'https://pubmed.ncbi.nlm.nih.gov/3/', 'Odd paper',
   'en', 'literature', '2026-11-05 08:00+00',
   '{"pmid":"3","oa":{"is_oa":true,"url":"javascript:alert(1)","license":"cc0","version":"weird"}}'),
  ('00000000-0000-0000-0000-00000068b004', 'ci-oa-lit', 'oa4', 'https://pubmed.ncbi.nlm.nih.gov/4/', 'New paper',
   'en', 'literature', '2026-11-05 08:00+00', '{"pmid":"4"}');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select paper_state(array['00000000-0000-0000-0000-00000068b001', '00000000-0000-0000-0000-00000068b002',
                         '00000000-0000-0000-0000-00000068b003', '00000000-0000-0000-0000-00000068b004']::uuid[])::text
  as oa_state \gset
reset role;

create temp table oa_res (j jsonb);
insert into oa_res values (:'oa_state'::jsonb);
create function pg_temp.oa_paper(doc text) returns jsonb language sql as $$
  select j -> ('00000000-0000-0000-0000-00000068' || doc) from oa_res
$$;

select pg_temp.oa_assert(
  pg_temp.oa_paper('b001') -> 'open_access' = '{"url":"https://europepmc.org/articles/PMC1","license":"cc-by",
                                                "version":"accepted","host_type":"repository"}'::jsonb,
  'an open paper carries its best location, licence, version and host type');
select pg_temp.oa_assert(
  pg_temp.oa_paper('b002') -> 'open_access' = 'null'::jsonb and pg_temp.oa_paper('b004') -> 'open_access' = 'null'::jsonb,
  'a closed paper and a paper not asked yet have no free full text');
select pg_temp.oa_assert(pg_temp.oa_paper('b003') -> 'open_access' = 'null'::jsonb,
  'an address that is not http(s) is never handed to the screen');
select pg_temp.oa_assert(
  pg_temp.oa_paper('b001') ->> 'day_zero' = '2026-11-05' and pg_temp.oa_paper('b001') ? 'case_report'
    and pg_temp.oa_paper('b001') ? 'issue_id' and pg_temp.oa_paper('b001') ? 'decision',
  'everything else paper_state() returned before 0068 is still there');
select pg_temp.oa_assert(
  not has_function_privilege('anon', 'public.paper_state(uuid[])', 'execute')
    and has_function_privilege('authenticated', 'public.paper_state(uuid[])', 'execute'),
  'paper_state() keeps its grants: signed-out visitors cannot call it');

rollback;
