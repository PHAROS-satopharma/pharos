-- PHAROS CI — case reports in the literature on the Ingredients screen (0044): paper_state() and
-- mlm_monitored(). Runs on the database ci.yml prepared: CI Admin (…a1) and CI Reader (…b2) exist. Everything
-- happens in one transaction that is rolled back at the end (review_event cannot be deleted).

begin;

create function pg_temp.cs_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.cs_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into ingredient (id, inn_en) values
  ('00000000-0000-0000-0000-00000044a001', 'CI casamine'),
  ('00000000-0000-0000-0000-00000044a002', 'CI mlmamine');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-CS-N', 'XN', 'CI Paperland', 'CI Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-cs-lit', 'CI-CS-N', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true);

-- Four papers. The first was found at 23:30 UTC on 3 November: already the 4th in Cairo.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-00000044b001', 'ci-cs-lit', '1', 'https://pubmed.ncbi.nlm.nih.gov/1/',
   'Hepatitis after CI casamine', 'en', 'literature', '2026-11-02', '2026-11-03 23:30+00', false,
   '{"pmid":"1","pubtype":["Journal Article","Case Reports"],"case_report":{"reason":"pubtype"}}'),
  ('00000000-0000-0000-0000-00000044b002', 'ci-cs-lit', '2', 'https://pubmed.ncbi.nlm.nih.gov/2/',
   'Rash with CI casamine: a case of DRESS', 'en', 'literature', '2026-11-05', '2026-11-05 08:00+00', false,
   '{"pmid":"2","pubtype":["Journal Article"]}'),                       -- stored before 0044: no flag yet
  ('00000000-0000-0000-0000-00000044b003', 'ci-cs-lit', '3', 'https://pubmed.ncbi.nlm.nih.gov/3/',
   'A cohort study of CI casamine', 'en', 'literature', '2026-11-05', '2026-11-05 08:00+00', false,
   '{"pmid":"3","pubtype":["Journal Article"]}'),
  ('00000000-0000-0000-0000-00000044b004', 'ci-cs-lit', '4', 'https://pubmed.ncbi.nlm.nih.gov/4/',
   'CI casamine: a case report, decided', 'en', 'literature', '2026-11-06', '2026-11-06 08:00+00', false,
   '{"pmid":"4","pubtype":["Case Reports"]}');
insert into issue (id, doc_type, title, anchor_document_id, first_date, is_backfill, class_only) values
  ('00000000-0000-0000-0000-00000044e001', 'literature', 'Hepatitis after CI casamine',
   '00000000-0000-0000-0000-00000044b001', '2026-11-02', false, false),
  ('00000000-0000-0000-0000-00000044e004', 'literature', 'CI casamine: a case report, decided',
   '00000000-0000-0000-0000-00000044b004', '2026-11-06', false, false),
  ('00000000-0000-0000-0000-00000044e009', 'literature', 'Suggested only', null, null, false, false);
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000044e001', '00000000-0000-0000-0000-00000044b001', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000044e004', '00000000-0000-0000-0000-00000044b004', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000044e009', '00000000-0000-0000-0000-00000044b002', 'copy', 'suggested');
insert into issue_ingredient values
  ('00000000-0000-0000-0000-00000044e001', '00000000-0000-0000-0000-00000044a001'),
  ('00000000-0000-0000-0000-00000044e004', '00000000-0000-0000-0000-00000044a001');

-- a decision on the fourth paper, by an administrator
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id)
  values ('00000000-0000-0000-0000-00000044e004', 'new', 'relevant', 'A serious case with our product',
          my_person_id());
reset role;

-- the backfill of 0044 flagged the papers stored before it (b002 above was inserted after it, so it tests the
-- answer worked out on the fly instead)
select count(*) as cs_unflagged
  from document d join source s on s.id = d.source_id
 where s.kind = 'literature' and d.structured -> 'case_report' is null
   and (coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports'
        or d.title_orig ~* '\m(case report|case reports|case series|a case of)\M')
   and d.id::text not like '00000000-0000-0000-0000-00000044b%' \gset

-- ───────────── the screen, as a reader ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select paper_state(array['00000000-0000-0000-0000-00000044b001', '00000000-0000-0000-0000-00000044b002',
                         '00000000-0000-0000-0000-00000044b003', '00000000-0000-0000-0000-00000044b004',
                         '00000000-0000-0000-0000-00000044bfff']::uuid[])::text as cs_state \gset
select paper_state('{}'::uuid[])::text as cs_empty \gset
select mlm_monitored('00000000-0000-0000-0000-00000044a001') as cs_mlm_a,
       mlm_monitored('00000000-0000-0000-0000-00000044a002') as cs_mlm_b \gset
select pg_temp.cs_refused($q$select paper_state(array_fill('00000000-0000-0000-0000-00000044b001'::uuid, array[1001]))$q$)
  as cs_too_many \gset
reset role;
insert into mlm_entry (ingredient_id, group_id, group_name, named_group, list_name, sha256, r2_key)
  values ('00000000-0000-0000-0000-00000044a002', 999, 'CI MLMAMINE', true, 'ci.xlsx', 'ef', 'raw/ef');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select mlm_monitored('00000000-0000-0000-0000-00000044a002') as cs_mlm_b2 \gset
reset role;

create temp table cs_res (j jsonb);
insert into cs_res values (:'cs_state'::jsonb);
create function pg_temp.cs_paper(doc text) returns jsonb language sql as $$
  select j -> ('00000000-0000-0000-0000-00000044' || doc) from cs_res
$$;

select pg_temp.cs_assert(:cs_unflagged = 0, 'every paper stored before 0044 that looks like a case report carries the flag');
select pg_temp.cs_assert(
  (select count(*) from cs_res, jsonb_object_keys(j)) = 4 and :'cs_empty' = '{}',
  'one entry per paper asked for; an unknown document has none; no papers, no entries');
select pg_temp.cs_assert(
  pg_temp.cs_paper('b001') -> 'case_report' = '{"reason":"pubtype"}'::jsonb
    and pg_temp.cs_paper('b001') ->> 'day_zero' = '2026-11-04'
    and pg_temp.cs_paper('b001') ->> 'due_serious' = '2026-11-19'
    and pg_temp.cs_paper('b001') ->> 'due_nonserious' = '2027-02-02'
    and pg_temp.cs_paper('b001') ->> 'issue_id' = '00000000-0000-0000-0000-00000044e001'
    and pg_temp.cs_paper('b001') ->> 'issue_status' = 'new'
    and pg_temp.cs_paper('b001') -> 'decision' = 'null'::jsonb,
  'a paper PubMed types Case Reports: the flag, day zero in Cairo, the 15- and 90-day dates, its notice, no decision');
select pg_temp.cs_assert(
  pg_temp.cs_paper('b002') -> 'case_report' = '{"reason":"title"}'::jsonb
    and pg_temp.cs_paper('b002') -> 'issue_id' = 'null'::jsonb,
  'a paper stored without the flag whose title says "a case of" is flagged on the fly; a suggestion is not its notice');
select pg_temp.cs_assert(
  pg_temp.cs_paper('b003') -> 'case_report' = 'null'::jsonb
    and pg_temp.cs_paper('b003') ->> 'day_zero' = '2026-11-05',
  'a cohort study is no case report; day zero is still given');
select pg_temp.cs_assert(
  pg_temp.cs_paper('b004') -> 'case_report' = '{"reason":"pubtype"}'::jsonb
    and pg_temp.cs_paper('b004') ->> 'issue_status' = 'relevant'
    and pg_temp.cs_paper('b004') -> 'decision' ->> 'to_status' = 'relevant'
    and pg_temp.cs_paper('b004') -> 'decision' ->> 'person' = 'CI Admin'
    and pg_temp.cs_paper('b004') -> 'decision' ->> 'comment' = 'A serious case with our product'
    and (pg_temp.cs_paper('b004') -> 'decision' ->> 'at') is not null,
  'a decided paper carries its status and the latest decision (who, when, comment)');
select pg_temp.cs_assert(not :'cs_mlm_a'::boolean and not :'cs_mlm_b'::boolean and :'cs_mlm_b2'::boolean,
  'an ingredient is monitored by EMA only while it has a row in the literature monitoring list');
select pg_temp.cs_assert(:'cs_too_many' like '22023%', 'more than 1,000 papers in one call are refused');

-- ───────────── who may ask ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.cs_refused($q$select paper_state(array['00000000-0000-0000-0000-00000044b001']::uuid[])$q$) as cs_stranger \gset
select pg_temp.cs_refused($q$select mlm_monitored('00000000-0000-0000-0000-00000044a001')$q$) as cs_stranger_mlm \gset
reset role;
select pg_temp.cs_assert(:'cs_stranger' like '42501%' and :'cs_stranger_mlm' like '42501%',
  'someone signed in but not on the team is refused');
-- the weekly report connects directly, with no sign-in token (screen_reader() of 0040)
select set_config('request.jwt.claims', '', false);
select pg_temp.cs_assert(
  paper_state(array['00000000-0000-0000-0000-00000044b001']::uuid[]) -> '00000000-0000-0000-0000-00000044b001' ->> 'day_zero'
    = '2026-11-04'
  and not mlm_monitored('00000000-0000-0000-0000-00000044a001'),
  'the report, on a direct connection, reads the same answers');
select pg_temp.cs_assert(
  not has_function_privilege('anon', 'public.paper_state(uuid[])', 'execute')
    and not has_function_privilege('anon', 'public.mlm_monitored(uuid)', 'execute')
    and has_function_privilege('authenticated', 'public.paper_state(uuid[])', 'execute')
    and has_function_privilege('authenticated', 'public.mlm_monitored(uuid)', 'execute'),
  'signed-out visitors can call neither');

rollback;
