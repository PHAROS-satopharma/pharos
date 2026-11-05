-- PHAROS CI — literature case reports and EMA's literature monitoring (0031). Runs on the database ci.yml
-- prepared: CI Reader (…b2) and the source ci-test exist.

create function pg_temp.cr_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

insert into ingredient (id, inn_en) values
  ('00000000-0000-0000-0000-00000006a001', 'CI casemab'),
  ('00000000-0000-0000-0000-00000006a002', 'CI watchedine');
insert into mlm_entry (ingredient_id, group_id, group_name, named_group, list_name, sha256, r2_key)
  values ('00000000-0000-0000-0000-00000006a002', 999, 'CI WATCHEDINE', true, 'ci.xlsx', 'ef', 'raw/ef');
-- The first paper was found at 23:30 UTC on 9 June 2025: already the 10th in Cairo.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, first_seen_at, structured) values
  ('00000000-0000-0000-0000-00000006b001', 'ci-test', 'cr1', 'https://example.test/cr1',
   'Hepatitis after CI casemab', 'en', 'literature', '2025-06-09 23:30+00',
   '{"pmid":"1","pubtype":["Journal Article","Case Reports"]}'),
  ('00000000-0000-0000-0000-00000006b002', 'ci-test', 'cr2', 'https://example.test/cr2',
   'Rash with CI watchedine: a case of DRESS', 'en', 'literature', '2025-06-01 08:00+00',
   '{"pmid":"2","pubtype":["Journal Article"]}'),
  ('00000000-0000-0000-0000-00000006b003', 'ci-test', 'cr3', 'https://example.test/cr3',
   'A cohort study of CI casemab', 'en', 'literature', '2025-06-01 08:00+00',
   '{"pmid":"3","pubtype":["Journal Article"]}');
insert into issue (id, doc_type, title, anchor_document_id) values
  ('00000000-0000-0000-0000-00000006c001', 'literature', 'Hepatitis after CI casemab', '00000000-0000-0000-0000-00000006b001'),
  ('00000000-0000-0000-0000-00000006c002', 'literature', 'Rash with CI watchedine: a case of DRESS', '00000000-0000-0000-0000-00000006b002'),
  ('00000000-0000-0000-0000-00000006c003', 'literature', 'A cohort study of CI casemab', '00000000-0000-0000-0000-00000006b003');
insert into issue_ingredient values
  ('00000000-0000-0000-0000-00000006c001', '00000000-0000-0000-0000-00000006a001'),
  ('00000000-0000-0000-0000-00000006c002', '00000000-0000-0000-0000-00000006a002'),
  ('00000000-0000-0000-0000-00000006c003', '00000000-0000-0000-0000-00000006a001');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select day_zero as cr_d0, serious_due as cr_15, nonserious_due as cr_90, flagged_by as cr_by,
       array_to_string(not_monitored, ',') as cr_nm
  from v_case_report where issue_id = '00000000-0000-0000-0000-00000006c001' \gset
select flagged_by as cr_by2, coalesce(array_to_string(not_monitored, ','), '') as cr_nm2
  from v_case_report where issue_id = '00000000-0000-0000-0000-00000006c002' \gset
select count(*) as cr_cohort from v_case_report where issue_id = '00000000-0000-0000-0000-00000006c003' \gset
select count(*) as cr_mlm from mlm_entry where ingredient_id = '00000000-0000-0000-0000-00000006a002' \gset
reset role;

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as cr_stranger from v_case_report \gset
reset role;

select pg_temp.cr_assert(:'cr_d0' = '2025-06-10' and :'cr_15' = '2025-06-25' and :'cr_90' = '2025-09-08',
  'day zero is the Cairo day PHAROS found the paper, with the 15- and 90-day dates');
select pg_temp.cr_assert(:'cr_by' = 'pubtype' and :'cr_by2' = 'title', 'the PubMed type Case Reports and a title both flag');
select pg_temp.cr_assert(:'cr_nm' = 'CI casemab' and :'cr_nm2' = '', 'an ingredient EMA does not monitor is named');
select pg_temp.cr_assert(:cr_cohort = 0, 'a cohort study is not a case report');
select pg_temp.cr_assert(:cr_mlm = 1, 'a reader reads the monitoring list');
select pg_temp.cr_assert(:cr_stranger = 0, 'someone not on the team sees no case report');

delete from issue where id::text like '00000000-0000-0000-0000-00000006c00%';
delete from document where id::text like '00000000-0000-0000-0000-00000006b00%';
delete from ingredient where id::text like '00000000-0000-0000-0000-00000006a00%';
