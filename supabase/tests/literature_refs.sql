-- PHAROS CI — Literature references, Global and Local (0101, Dr Sama, 8 Nov 2026). Runs on the database ci.yml
-- prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. One transaction, rolled back at the end.

begin;

create function pg_temp.lr_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.lr_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- ───────────── her references are there from the start ─────────────
select pg_temp.lr_assert((select count(*) from literature_ref where active and scope = 'global'
                            and name in ('PubMed (NCBI)', 'PubMed Central (NCBI)', 'Europe PMC',
                                         'Cochrane Database of Systematic Reviews', 'Medscape')) = 5,
  'Global holds PubMed, PubMed Central, Europe PMC, Cochrane and Medscape');
select pg_temp.lr_assert((select count(*) from literature_ref where active and scope = 'local'
                            and name in ('Al-Azhar Medical Journal', 'Ain Shams Medical Journal')) = 2,
  'Local holds the Al-Azhar and Ain Shams medical journals');
select pg_temp.lr_assert((select searched_in = '{}' from literature_ref where name = 'Medscape')
                         and (select searched_in = '{pubmed,europepmc}' and journal_like = 'cochrane database'
                                from literature_ref where name = 'Cochrane Database of Systematic Reviews'),
  'Medscape is checked by hand; Cochrane is counted from the PubMed and Europe PMC searches');

-- ───────────── as an admin: add, change, remove ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', true);
set local role authenticated;
insert into literature_ref (id, scope, name, url) values
  ('00000000-0000-0000-0000-000000101f01', 'local', 'CI Egyptian Journal', 'https://ci-ejournal.example.test/');
update literature_ref set name = 'CI Egyptian Medical Journal' where id = '00000000-0000-0000-0000-000000101f01';
insert into literature_ref (id, scope, name, url) values
  ('00000000-0000-0000-0000-000000101f02', 'global', 'CI Removed', 'https://ci-removed.example.test/');
delete from literature_ref where id = '00000000-0000-0000-0000-000000101f02';
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_ref (scope, name, url)
                        values ('local', 'CI Twin', 'https://CI-EJOURNAL.example.test/')$q$) like '23505 %',
  'the same address is not added twice in one list');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_ref (scope, name, url)
                        values ('local', 'CI Script', 'javascript:alert(1)')$q$) like '23514 %',
  'an address is http or https only');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_ref (scope, name, url)
                        values ('regional', 'CI Region', 'https://ci-region.example.test/')$q$) like '23514 %',
  'a reference is Global or Local');
reset role;

select pg_temp.lr_assert((select name = 'CI Egyptian Medical Journal' and created_by =
                                 (select id from person where email = 'admin@example.test')
                            from literature_ref where id = '00000000-0000-0000-0000-000000101f01'),
  'an admin adds and renames a local reference, and it names who added it');
select pg_temp.lr_assert(exists (select 1 from audit_log where table_name = 'literature_ref' and action = 'UPDATE'
                                    and old_row ->> 'name' = 'CI Egyptian Journal'
                                    and new_row ->> 'name' = 'CI Egyptian Medical Journal'
                                    and actor = '00000000-0000-0000-0000-0000000000a1'),
  'the change is in the audit log, with the admin who made it');
select pg_temp.lr_assert(exists (select 1 from audit_log where table_name = 'literature_ref' and action = 'DELETE'
                                    and old_row ->> 'name' = 'CI Removed'),
  'a removed reference stays in the audit log');

-- ───────────── a reader changes nothing and records no check ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', true);
set local role authenticated;
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_ref (scope, name, url)
                        values ('local', 'CI Reader''s', 'https://ci-reader.example.test/')$q$) like '42501 %',
  'a reader adds no reference');
update literature_ref set name = 'CI changed by a reader' where id = '00000000-0000-0000-0000-000000101f01';
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$select record_literature_check('00000000-0000-0000-0000-000000101f01', 'nothing')$q$)
    like '42501 %',
  'a reader records no check');
select pg_temp.lr_assert((select count(*) from literature_ref where scope = 'global') >= 5,
  'a reader reads the references');
reset role;
select pg_temp.lr_assert((select name from literature_ref where id = '00000000-0000-0000-0000-000000101f01')
                          = 'CI Egyptian Medical Journal',
  'a reader''s change does not land');

-- ───────────── a reviewer records a hand check; nobody edits it ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', true);
set local role authenticated;
select record_literature_check('00000000-0000-0000-0000-000000101f01', 'nothing', '  ') as lr_check \gset
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$select record_literature_check('00000000-0000-0000-0000-000000101f01', 'found', '')$q$)
    like '22023 %',
  'something found says what was found');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$select record_literature_check('00000000-0000-0000-0000-000000101f01', 'maybe')$q$)
    like '22023 %',
  'a check is nothing found or found');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_check (ref_id, result, checked_by)
                        select '00000000-0000-0000-0000-000000101f01', 'nothing', id from person limit 1$q$)
    like '42501 %',
  'a check is recorded only through the function');
select pg_temp.lr_assert(
  pg_temp.lr_refused(format($q$update literature_check set result = 'found' where id = %L$q$, :'lr_check'))
    like '42501 %'
  and pg_temp.lr_refused(format($q$delete from literature_check where id = %L$q$, :'lr_check')) like '42501 %',
  'nobody changes or removes a check');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$insert into literature_search_log (source_id, db, query, kind, window_from, window_to, hits)
                        values ('pubmed', 'pubmed', 'x', 'name', '2026-11-01', '2026-11-01', 0)$q$) like '42501 %',
  'the team writes nothing to the search log');
reset role;
select pg_temp.lr_assert((select result = 'nothing' and note is null and checked_at > now() - interval '1 hour'
                                 and checked_by = (select id from person where email = 'reviewer@example.test')
                            from literature_check where id = :'lr_check'),
  'the check names the reviewer and the database time, and cannot be changed or removed');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$delete from literature_ref where id = '00000000-0000-0000-0000-000000101f01'$q$)
    like '23503 %',
  'a reference with a check on it is switched off, never deleted');

-- ───────────── the week of one ingredient, reference by reference ─────────────
insert into ingredient (id, inn_en, atc_code) values ('00000000-0000-0000-0000-000000101a01', 'CI Refamine', 'Z99ZZ01');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-000000101c01', '00000000-0000-0000-0000-000000101a01', 'en', 'CI Refamine');
insert into regulator (id, country_code, country_name, name, languages) values
  ('CI-LR', 'XN', 'CI Paperland', 'CI Library', '{en}');
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-lr-ncbi', 'CI-LR', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true);
insert into run (id, trigger) values ('00000000-0000-0000-0000-000000101b01', 'manual');

-- The week of Sunday 1 to Saturday 7 Nov 2026: PubMed searched twice (3 then 0 papers), PMC once (0 papers);
-- one search the week after, one for another word.
insert into literature_search_log (run_id, source_id, db, query, kind, window_from, window_to, hits, searched_at) values
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-ncbi', 'pubmed', 'ci refamine', 'name', '2026-11-01', '2026-11-02', 3,
   '2026-11-02 05:00+00'),
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-ncbi', 'pubmed', 'ci refamine', 'name', '2026-11-02', '2026-11-03', 0,
   '2026-11-03 05:00+00'),
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-ncbi', 'pmc', 'ci refamine', 'name', '2026-11-02', '2026-11-03', 0,
   '2026-11-03 05:00+00'),
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-ncbi', 'pubmed', 'ci refamine', 'name', '2026-11-08', '2026-11-09', 1,
   '2026-11-09 05:00+00'),
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-ncbi', 'pubmed', 'ci otheramine', 'name', '2026-11-02', '2026-11-03', 9,
   '2026-11-03 05:00+00');

-- Two papers in the week: a Cochrane review PubMed found, and a paper only Europe PMC found.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-000000101e01', 'ci-lr-ncbi', 'lr1', 'https://pubmed.ncbi.nlm.nih.gov/101/',
   'CI Refamine for pain', 'en', 'literature', '2026-11-02', '2026-11-02 08:00+00', false,
   '{"journal":"The Cochrane database of systematic reviews","found_in":["pubmed"]}'),
  ('00000000-0000-0000-0000-000000101e02', 'ci-lr-ncbi', 'lr2', 'https://europepmc.org/article/MED/102',
   'CI Refamine in rats', 'en', 'literature', '2026-11-03', '2026-11-03 08:00+00', false,
   '{"journal":"CI_Journal 100%","found_in":["europepmc"]}');
insert into match (document_id, ingredient_id, term_id, field, matched_text)
  select d, '00000000-0000-0000-0000-000000101a01', '00000000-0000-0000-0000-000000101c01', 'structured', 'CI Refamine'
    from unnest(array['00000000-0000-0000-0000-000000101e01', '00000000-0000-0000-0000-000000101e02']::uuid[]) as d;

-- Medscape, checked by the reviewer twice in the week: something found on Tuesday, nothing on Thursday. A check
-- is never changed, so the week's checks are written as they would have been, with their day.
insert into literature_check (ref_id, result, note, checked_by, checked_at)
  select r.id, x.result, x.note, p.id, x.at::timestamptz
    from literature_ref r, person p,
         (values ('found', 'CI case report of CI Refamine', '2026-11-03 10:00+00'),
                 ('nothing', null, '2026-11-05 10:00+00')) as x(result, note, at)
   where r.name = 'Medscape' and p.email = 'reviewer@example.test';

-- a local journal checked in the week, then removed: its check stays in the week's record
insert into literature_ref (id, scope, name, url) values
  ('00000000-0000-0000-0000-000000101f03', 'local', 'CI Old Journal', 'https://ci-old.example.test/');
insert into literature_check (ref_id, result, checked_by, checked_at)
  select '00000000-0000-0000-0000-000000101f03', 'nothing', p.id, '2026-11-04 10:00+00'
    from person p where p.email = 'reviewer@example.test';
update literature_ref set active = false where id = '00000000-0000-0000-0000-000000101f03';

-- a Europe PMC read that failed in the week
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-lr-epmc', 'CI-LR', 'literature', 'api', 'https://epmc.example.test/', 'europepmc', '{en}',
   'https://europepmc.example.test/', true);
insert into source_run (run_id, source_id, started_at, finished_at, error) values
  ('00000000-0000-0000-0000-000000101b01', 'ci-lr-epmc', '2026-11-04 05:00+00', '2026-11-04 05:01+00',
   'HTTP 503 from epmc.example.test');

-- ───────────── evidence: nobody changes or removes a search or a check, the owner included ─────────────
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$update literature_check set result = 'nothing' where result = 'found'$q$) like '42501 %'
  and pg_temp.lr_refused($q$delete from literature_check$q$) like '42501 %'
  and pg_temp.lr_refused($q$truncate literature_check$q$) like '42501 %',
  'a hand check is never changed or removed, by the owner either');
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$update literature_search_log set hits = 0 where query = 'ci refamine'$q$) like '42501 %'
  and pg_temp.lr_refused($q$delete from literature_search_log where query = 'ci refamine'$q$) like '42501 %'
  and pg_temp.lr_refused($q$truncate literature_search_log$q$) like '42501 %',
  'a logged search is never changed or removed, by the owner either');

-- read as CI Reader; the temp tables that keep the answers are made by the owner
create temp table lr_week (e jsonb);
create temp table lr_all (e jsonb);
grant insert on lr_week, lr_all to authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', true);
set local role authenticated;
insert into lr_week select e from jsonb_array_elements(
  literature_refs_week('00000000-0000-0000-0000-000000101a01', '2026-11-01', '2026-11-07')) e;
insert into lr_all select e from jsonb_array_elements(literature_refs_week(null, '2026-11-01', '2026-11-07')) e;
reset role;

select pg_temp.lr_assert((select (e ->> 'searches')::int = 2 and (e ->> 'name_searches')::int = 2
                                 and (e ->> 'hits')::int = 3 and (e ->> 'found')::int = 1
                                 and (e ->> 'failed_reads')::int = 0
                            from lr_week where e ->> 'name' = 'PubMed (NCBI)'),
  'PubMed: two searches of the ingredient''s name that week, 3 papers returned, 1 of its papers found');
select pg_temp.lr_assert((select (e ->> 'searches')::int = 1 and (e ->> 'hits')::int = 0 and (e ->> 'found')::int = 0
                            from lr_week where e ->> 'name' = 'PubMed Central (NCBI)'),
  'PubMed Central: searched once, nothing found — the zero is on record');
select pg_temp.lr_assert((select (e ->> 'searches')::int = 0 and (e ->> 'found')::int = 1
                                 and (e ->> 'failed_reads')::int = 1
                            from lr_week where e ->> 'name' = 'Europe PMC'),
  'Europe PMC: its paper counts, and the failed read of the week is there to see');
select pg_temp.lr_assert((select (e ->> 'searches')::int = 2 and (e ->> 'found')::int = 1
                            from lr_week where e ->> 'name' = 'Cochrane Database of Systematic Reviews'),
  'Cochrane: counted from the searches, only the papers in its journal');
select pg_temp.lr_assert((select (e ->> 'by_hand')::boolean and e -> 'found' = 'null'::jsonb
                                 and e -> 'check' ->> 'result' = 'found'
                                 and e -> 'check' ->> 'note' = 'CI case report of CI Refamine'
                                 and e -> 'check' ->> 'checked_by' = 'CI Reviewer'
                                 and (e ->> 'checks')::int = 2 and (e ->> 'found_checks')::int = 1
                            from lr_week where e ->> 'name' = 'Medscape'),
  'Medscape: what was found on Tuesday speaks for the week, though nothing was found on Thursday');
select pg_temp.lr_assert((select not (e ->> 'active')::boolean and e -> 'check' ->> 'result' = 'nothing'
                            from lr_week where e ->> 'name' = 'CI Old Journal'),
  'a reference removed since keeps its check in the week''s record');
select pg_temp.lr_assert((select e -> 'check' = 'null'::jsonb from lr_week where e ->> 'name' = 'Al-Azhar Medical Journal'),
  'Al-Azhar: no check that week, and none is made up');
select pg_temp.lr_assert((select (e ->> 'searches')::int = 3 and (e ->> 'hits')::int = 12 and e -> 'found' = 'null'::jsonb
                            from lr_all where e ->> 'name' = 'PubMed (NCBI)'),
  'with no ingredient: every PubMed search of the week, any word');

set local role anon;
select pg_temp.lr_assert(
  pg_temp.lr_refused($q$select literature_refs_week(null, '2026-11-01', '2026-11-07')$q$) like '42501 %',
  'nobody signed out reads the references');
reset role;

rollback;
