-- PHAROS CI — the free terminologies (0103). Runs after every migration and the acceptance checks in ci.yml, on the
-- same database: the people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Every code and name is
-- invented; no MedDRA content is anywhere here.

create function pg_temp.ci_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into term_release (source, version, sha256, status, concepts, names)
values ('ncit', 'CI 99.01a', repeat('a', 64), 'active', 4, 6);
insert into term_concept (source, code, name, definition, subsets, status) values
  ('ncit', 'C9000001', 'Test Adverse Event', 'Any test event.', '{}', 'current'),
  ('ncit', 'C9000002', 'Test Insomnia', 'Cannot sleep, in a test.', '{"CTCAE Adverse Events Version 6.0 Terminology"}', 'current'),
  ('ncit', 'C9000003', 'Test Insomnia, CTCAE Grade 1', 'Mild.', '{"CTCAE Adverse Events Version 6.0 Terminology"}', 'current'),
  ('ncit', 'C9000004', 'Test Old Sleep Word', null, '{}', 'retired'),
  ('ncit', 'C9000006', 'Test Wakeful', null, '{}', 'retired'),
  ('ncit', 'C9000007', 'Test Wakefulness', null, '{}', 'current'),
  ('oae',  'OAE_9000001', 'test insomnia AE', null, '{}', 'current'),
  ('icd11', '9Z99', 'Test insomnia', null, '{}', 'current');
insert into term_name (source, code, name, lang, preferred) values
  ('ncit', 'C9000001', 'Test Adverse Event', 'en', true),
  ('ncit', 'C9000002', 'Test Insomnia', 'en', true),
  ('ncit', 'C9000002', 'Test Sleeplessness', 'en', false),
  ('ncit', 'C9000003', 'Test Insomnia, CTCAE Grade 1', 'en', true),
  ('ncit', 'C9000004', 'Test Sleeplessness Old', 'en', true),
  ('ncit', 'C9000006', 'Test Wakeful', 'en', true),
  ('ncit', 'C9000007', 'Test Wakefulness', 'en', true),
  ('oae',  'OAE_9000001', 'test insomnia AE', 'en', true),
  ('oae',  'OAE_9000001', 'Test Sleeplessness', 'en', false),
  ('icd11', '9Z99', 'Test insomnia', 'en', true),
  ('icd11', '9Z99', 'أرق تجريبي', 'ar', false);
insert into term_parent (source, code, parent) values
  ('ncit', 'C9000002', 'C9000001'), ('ncit', 'C9000003', 'C9000002'), ('ncit', 'C9000004', 'C9000001');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select code from term_search('C9000002') limit 1) = 'C9000002'
                         and (select match from term_search('C9000002') limit 1) = 'code', 'a code finds its concept');
select pg_temp.ci_assert((select code from term_search('oae_9000001') limit 1) = 'OAE_9000001',
                         'a code typed in lower case is found');
select pg_temp.ci_assert((select (source, code, match) = ('ncit', 'C9000002', 'exact')
                            from term_search('test sleeplessness', array['ncit']) limit 1),
                         'the exact name comes first, found as its synonym');
select pg_temp.ci_assert((select found_as from term_search('test sleeplessness', array['ncit']) limit 1)
                         = 'Test Sleeplessness', 'found_as names the synonym that matched');
select pg_temp.ci_assert((select array_agg(code order by 1) from term_search('test sleeplessness', array['ncit']))
                         @> array['C9000002', 'C9000004'], 'a retired concept is still found');
select pg_temp.ci_assert((select array_agg(code) from term_search('test wakeful', array['ncit']))
                         = array['C9000007', 'C9000006'],
                         'a current concept comes before a retired one, even one whose name is exact');
select pg_temp.ci_assert((select match from term_search('test insom', array['ncit']) limit 1) = 'prefix',
                         'the start of a name is found');
select pg_temp.ci_assert((select count(*) from term_search('test insomnai', array['ncit'])) >= 1,
                         'a misspelling is found by likeness');
select pg_temp.ci_assert((select code from term_search('أرق تجريبي') limit 1) = '9Z99',
                         'an Arabic ICD-11 title is found');
select pg_temp.ci_assert((select count(*) from term_search('test sleeplessness', array['icd11'])) = 0,
                         'a source filter keeps to that source');
select pg_temp.ci_assert((select count(*) from term_search('%')) = 0 and (select count(*) from term_search('')) = 0,
                         'a wildcard or nothing is not a search');
select pg_temp.ci_assert((select version from term_lookup('ncit', 'C9000002')) = 'CI 99.01a'
                         and (select licence from term_lookup('ncit', 'C9000002')) like 'NCI Thesaurus%',
                         'a code is named with its version and licence');
select pg_temp.ci_assert((select jsonb_array_length(names) from term_lookup('ncit', 'C9000002')) = 2,
                         'with all its names');
select pg_temp.ci_assert((select count(*) from term_lookup('ncit', 'C1234567')) = 0, 'an unknown code has no row');
select pg_temp.ci_assert((select array_agg(code order by depth) from term_path('ncit', 'C9000003'))
                         = array['C9000001', 'C9000002', 'C9000003'], 'the path runs from the top down');
select pg_temp.ci_assert((select array_agg(code order by code) from term_children('ncit', 'C9000001'))
                         = array['C9000002', 'C9000004'], 'the children of a concept');
select pg_temp.ci_assert((select children from term_children('ncit', 'C9000001') where code = 'C9000002') = 1,
                         'each child says how many children it has');
select pg_temp.ci_assert((select (source, code, note) = ('oae', 'OAE_9000001', 'Same words, not an official mapping')
                            from term_related('ncit', 'C9000002')),
                         'another source with the same words is related, never called a mapping');
select pg_temp.ci_assert((select count(*) from term_related('ncit', 'C9000002') where source = 'icd11') = 0
                         and (select count(*) from term_related('icd11', '9Z99')) = 0,
                         'ICD-11 is never compared with another source');
select pg_temp.ci_assert(pg_temp.refused($$insert into term_concept (source, code, name)
                                            values ('ncit', 'C9000009', 'x')$$) like '42501%',
                         'nobody in the app writes the terminologies');
reset role;

-- A staged release: one concept changed, one added under it, one retired.
insert into term_release (source, version, sha256, status, concepts, names, added, changed, retired)
values ('ncit', 'CI 99.02a', repeat('b', 64), 'staged', 4, 6, 1, 1, 1);
insert into term_change (release, source, code, kind, before, after)
select id, 'ncit', 'C9000005', 'added', null::jsonb,
       '{"name": "Test Nightmare", "names": [["Test Nightmare", "en", true], ["Test Bad Dream", "en", false]],
         "parents": ["C9000002"], "subsets": []}'::jsonb
  from term_release where version = 'CI 99.02a'
union all
select id, 'ncit', 'C9000002', 'changed', '{"name": "Test Insomnia"}',
       '{"name": "Test Insomnia Disorder", "definition": "Cannot sleep.",
         "names": [["Test Insomnia Disorder", "en", true], ["Test Sleeplessness", "en", false]],
         "parents": ["C9000001"], "subsets": ["CTCAE Adverse Events Version 6.0 Terminology"]}'::jsonb
  from term_release where version = 'CI 99.02a'
union all
select id, 'ncit', 'C9000001', 'retired', '{"name": "Test Adverse Event"}', null::jsonb
  from term_release where version = 'CI 99.02a';
select id as staged from term_release where version = 'CI 99.02a' \gset

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert(pg_temp.refused(format('select activate_term_release(%s)', :staged)) like '42501%',
                         'a reviewer cannot activate a release');
select pg_temp.ci_assert(pg_temp.refused(format('select reject_term_release(%s)', :staged)) like '42501%',
                         'nor reject one');
select pg_temp.ci_assert((select count(*) from term_search('test nightmare', array['ncit'])) = 0,
                         'a staged release changes nothing until it is activated');
reset role;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select activate_term_release(:staged);
select pg_temp.ci_assert(pg_temp.refused(format('select activate_term_release(%s)', :staged)) like '22023%',
                         'a release is activated once');
reset role;
select pg_temp.ci_assert((select status from term_release where version = 'CI 99.02a') = 'active'
                         and (select activated_by from term_release where version = 'CI 99.02a')
                             = (select id from person where email = 'admin@example.test')
                         and (select status from term_release where version = 'CI 99.01a') = 'superseded',
                         'the activated release is active, named with who did it; the one before is superseded');
select pg_temp.ci_assert((select name from term_concept where code = 'C9000002') = 'Test Insomnia Disorder'
                         and exists (select 1 from term_name where code = 'C9000002' and name = 'Test Insomnia Disorder')
                         and not exists (select 1 from term_name where code = 'C9000002' and name = 'Test Insomnia'),
                         'a changed concept carries its new names only');
select pg_temp.ci_assert((select (status, retired_in) = ('retired', :staged::bigint) from term_concept
                           where code = 'C9000001'), 'a retired concept stays, marked with the release');
select pg_temp.ci_assert(exists (select 1 from term_parent where code = 'C9000005' and parent = 'C9000002')
                         and (select first_release from term_concept where code = 'C9000005') = :staged,
                         'an added concept sits under its parent, from this release');
select pg_temp.ci_assert((select count(*) from term_change where release = :staged) = 3,
                         'the changes stay as history');

-- A second staged release is rejected.
insert into term_release (source, version, sha256, status) values ('ncit', 'CI 99.03a', repeat('c', 64), 'staged');
select id as staged2 from term_release where version = 'CI 99.03a' \gset
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select reject_term_release(:staged2, 'CI: looks wrong');
reset role;
select pg_temp.ci_assert((select (status, note) = ('rejected', 'CI: looks wrong') from term_release
                           where id = :staged2), 'a rejected release says why');

-- A confirmed case teaches the search: the concept chosen before for the same words comes first.
insert into safety_case (id, ref, origin, status, day_zero, r2_key, sha256, data) values
  ('00000000-0000-0000-0000-00000103c001', 'CASE-CI-0103-1', 'upload', 'confirmed', '2026-11-01', 'sha256/ci/0103',
   'ci0103', '{"reactions": [{"verbatim": "Test Sleeplessness", "term": {"source": "oae", "code": "OAE_9000001"}}]}');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select (source, code, chosen_before) = ('oae', 'OAE_9000001', 1)
                            from term_search('test sleeplessness') limit 1),
                         'the concept chosen before for the same words comes first');
reset role;

set role anon;
select pg_temp.ci_assert(pg_temp.refused($$select * from term_search('test')$$) like '42501%',
                         'the public key cannot search');
reset role;

delete from safety_case where id = '00000000-0000-0000-0000-00000103c001';
delete from term_change;
delete from term_parent;
delete from term_name;
delete from term_concept;
delete from term_release;
