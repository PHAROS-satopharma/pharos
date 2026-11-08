-- PHAROS CI — the MedDRA dictionary (0102). Runs after every migration and the acceptance checks in ci.yml, on the
-- same database: the people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Every code and term is
-- invented: MedDRA's own are licensed and never belong in this public repository.

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

insert into coding_dictionary (name, version, release, source_url, sha256, descriptors, terms)
values ('meddra', 'MedDRA 99.1 English', '99.1', 'uploads/20261110T080000Z', 'ci', 2, 4);
insert into meddra_pt (code, name, hlt_name, hlgt_name, soc_code, soc_name) values
  ('90000001', 'Test sleeplessness', 'Test sleep HLT', 'Test sleep HLGT', '90000100', 'Test mind SOC'),
  ('90000002', 'Test itching', 'Test itch HLT', 'Test itch HLGT', '90000200', 'Test skin SOC');
insert into meddra_llt (code, name, pt_code, current) values
  ('90000001', 'Test sleeplessness', '90000001', true),
  ('90000003', 'Test cannot sleep', '90000001', true),
  ('90000004', 'Test sleeplessness old', '90000001', false),
  ('90000002', 'Test itching', '90000002', true);

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select llt_code from meddra_search('test sleeplessness') limit 1) = '90000001',
                         'the exact name comes first');
select pg_temp.ci_assert((select soc_name from meddra_search('test sleeplessness') limit 1) = 'Test mind SOC',
                         'the LLT comes with its PT and primary SOC');
select pg_temp.ci_assert((select (array_agg(llt_code))[1] = '90000001'
                                 and (array_agg(llt_code))[count(*)::int] = '90000004'
                            from meddra_search('test sleeplessnes')),
                         'a current LLT comes before a non-current one');
select pg_temp.ci_assert((select llt_name from meddra_search('90000003')) = 'Test cannot sleep',
                         'an 8-digit code finds its LLT');
select pg_temp.ci_assert((select count(*) from meddra_search('te')) = 0, 'two letters are not a search');
select pg_temp.ci_assert((select release from meddra_lookup('90000002')) = '99.1', 'a code is named with the version');
select pg_temp.ci_assert((select count(*) from meddra_lookup('12345678')) = 0, 'a code not in MedDRA has no row');
select pg_temp.ci_assert(pg_temp.refused($$insert into meddra_llt (code, name, pt_code, current)
                                            values ('90000009', 'Sick', '90000001', true)$$) like '42501%',
                         'nobody in the app writes the dictionary');
select pg_temp.ci_assert(pg_temp.refused($$select ask_meddra_load('uploads/20261110T090000Z')$$) like '42501%',
                         'a reader cannot ask for a load');
reset role;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert(pg_temp.refused($$select ask_meddra_load('uploads/20261110T090000Z')$$) like '42501%',
                         'a reviewer cannot ask for a load either');
reset role;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert(pg_temp.refused($$select ask_meddra_load('../etc')$$) like '22023%',
                         'an upload folder is only uploads/<UTC time>');
select ask_meddra_load('uploads/20261110T090000Z');
select pg_temp.ci_assert((select status from meddra_upload where folder = 'uploads/20261110T090000Z') = 'waiting',
                         'an administrator asks for the load');
reset role;

-- A confirmed case teaches the search: the same words find the LLT chosen before, first.
insert into safety_case (id, ref, origin, status, day_zero, r2_key, sha256, data) values
  ('00000000-0000-0000-0000-00000102c001', 'CASE-CI-0102-1', 'upload', 'confirmed', '2026-11-01', 'sha256/ci/0102',
   'ci0102', '{"reactions": [{"verbatim": "test sleeplessness", "meddra_llt_code": "90000003", "meddra_version": "99.1"}]}');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select llt_code from meddra_search('Test sleeplessness') limit 1) = '90000003',
                         'the LLT chosen before for the same words comes first');
select pg_temp.ci_assert((select chosen_before from meddra_search('Test sleeplessness') limit 1) = 1,
                         'with how many cases chose it');
reset role;

delete from safety_case where id = '00000000-0000-0000-0000-00000102c001';
delete from meddra_upload;
delete from meddra_llt;
delete from meddra_pt;
delete from coding_dictionary where name = 'meddra';
