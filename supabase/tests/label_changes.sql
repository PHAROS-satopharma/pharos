-- PHAROS CI — our label under "Label changes" (0043): label_changes(), label_gap, spc_product.is_reference and
-- set_reference_product(). Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and
-- CI Reviewer (…c3) exist. Everything here happens in one transaction that is rolled back at the end.

begin;

create function pg_temp.lc_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.lc_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- The change ids of an answer, in its order, as "c001,c002".
create function pg_temp.lc_ids(j jsonb) returns text language sql as $$
  select coalesce(string_agg(right(x ->> 'change_id', 4), ',' order by n), '')
    from jsonb_array_elements(j) with ordinality as t(x, n)
$$;

-- ───────────── two ingredients, one label-watch source, three products ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000043a001', 'CI labelamine', 'Z96ZZ01'),
  ('00000000-0000-0000-0000-00000043a002', 'CI otherlabelamine', 'Z96ZZ02');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-LC-A', 'XL', 'CI Labelland', 'CI Labelland Agency', '{en}', 'https://label.example.test/');
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-lc-spc', 'CI-LC-A', 'spc', 'api', 'https://label.example.test/spc.json', 'ci', '{en}',
   'https://label.example.test/products', true);
insert into spc_product (id, ingredient_id, source_id, country_code, national_id, product_name, mah, url) values
  ('00000000-0000-0000-0000-00000043p001', '00000000-0000-0000-0000-00000043a001', 'ci-lc-spc', 'XL', 'LC-1',
   'CI Labelamine Originator 10 mg', 'CI Originator Ltd', 'https://label.example.test/products/1'),
  ('00000000-0000-0000-0000-00000043p002', '00000000-0000-0000-0000-00000043a001', 'ci-lc-spc', 'XL', 'LC-2',
   'CI Labelamine Generic 10 mg', 'CI Generics', null),
  ('00000000-0000-0000-0000-00000043p003', '00000000-0000-0000-0000-00000043a002', 'ci-lc-spc', 'XL', 'LC-3',
   'CI Otherlabelamine 5 mg', null, null);
insert into spc_snapshot (id, spc_product_id, fetched_at, doc_date, sha256, section_hashes) values
  ('00000000-0000-0000-0000-00000043s001', '00000000-0000-0000-0000-00000043p001', '2026-06-02 08:00+00', '2026-06-01', 'a1', '{}'),
  ('00000000-0000-0000-0000-00000043s002', '00000000-0000-0000-0000-00000043p001', '2026-11-03 09:00+00', '2026-10-01', 'a2', '{}'),
  ('00000000-0000-0000-0000-00000043s003', '00000000-0000-0000-0000-00000043p002', '2026-06-02 08:00+00', '2026-05-01', 'b1', '{}'),
  ('00000000-0000-0000-0000-00000043s004', '00000000-0000-0000-0000-00000043p002', '2026-11-05 08:00+00', '2026-11-01', 'b2', '{}'),
  ('00000000-0000-0000-0000-00000043s005', '00000000-0000-0000-0000-00000043p003', '2026-06-02 08:00+00', null, 'c1', '{}'),
  ('00000000-0000-0000-0000-00000043s006', '00000000-0000-0000-0000-00000043p003', '2026-11-04 08:00+00', null, 'c2', '{}'),
  ('00000000-0000-0000-0000-00000043s007', '00000000-0000-0000-0000-00000043p002', '2026-10-20 08:00+00', '2026-10-15', 'b0', '{}'),
  ('00000000-0000-0000-0000-00000043s008', '00000000-0000-0000-0000-00000043p001', '2026-11-07 22:30+00', '2026-11-07', 'a3', '{}');

-- The alerting change of the originator: a document and a notice, as collectors/spc/run.py writes them.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-00000043b001', 'ci-lc-spc', 'spc:LC-1:a2', 'https://label.example.test/products/1',
   'CI Labelamine Originator 10 mg — 4.4', 'en', 'label_change', '2026-10-01', '2026-11-03 09:00+00', false,
   '{"sections":["4.4"]}');
insert into match (document_id, ingredient_id, field, matched_text) values
  ('00000000-0000-0000-0000-00000043b001', '00000000-0000-0000-0000-00000043a001', 'structured', 'CI Labelamine Originator 10 mg');
insert into issue (id, doc_type, title, anchor_document_id, first_date, is_backfill, class_only) values
  ('00000000-0000-0000-0000-00000043e001', 'label_change', 'CI Labelamine Originator 10 mg — 4.4',
   '00000000-0000-0000-0000-00000043b001', '2026-10-01', false, false);
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000043e001', '00000000-0000-0000-0000-00000043b001', 'anchor', 'auto');
insert into issue_ingredient (issue_id, ingredient_id) values
  ('00000000-0000-0000-0000-00000043e001', '00000000-0000-0000-0000-00000043a001');

-- c001: the originator's 4.4, detected Tue 3 Nov (label dated 1 Oct); c002: the generic's section 10 only,
-- detected 5 Nov, no notice; c003: detected 20 Oct (before the week); c004: another ingredient;
-- c005: detected Saturday 7 Nov 22:30 UTC = Sunday 8 Nov 00:30 in Cairo (after the week).
insert into spc_change (id, spc_product_id, from_snapshot, to_snapshot, sections, diff, issue_id, created_at) values
  ('00000000-0000-0000-0000-00000043c001', '00000000-0000-0000-0000-00000043p001',
   '00000000-0000-0000-0000-00000043s001', '00000000-0000-0000-0000-00000043s002', '{4.4}',
   '[{"section":"4.4","before":"Use with caution in renal impairment.",'
   '"after":"Use with caution in renal impairment. Cases of acute kidney injury have been reported.",'
   '"changes":[{"op":"insert","before":"","after":"Cases of acute kidney injury have been reported.",'
   '"context":"Use with caution in renal impairment."}]}]',
   '00000000-0000-0000-0000-00000043e001', '2026-11-03 09:00+00'),
  ('00000000-0000-0000-0000-00000043c002', '00000000-0000-0000-0000-00000043p002',
   '00000000-0000-0000-0000-00000043s003', '00000000-0000-0000-0000-00000043s004', '{10}',
   '[{"section":"10","before":"May 2026","after":"November 2026","changes":[]}]', null, '2026-11-05 08:00+00'),
  ('00000000-0000-0000-0000-00000043c003', '00000000-0000-0000-0000-00000043p002',
   '00000000-0000-0000-0000-00000043s003', '00000000-0000-0000-0000-00000043s007', '{4.8}',
   '[{"section":"4.8","before":"Nausea.","after":"Nausea. Headache.","changes":[]}]', null, '2026-10-20 08:00+00'),
  ('00000000-0000-0000-0000-00000043c004', '00000000-0000-0000-0000-00000043p003',
   '00000000-0000-0000-0000-00000043s005', '00000000-0000-0000-0000-00000043s006', '{4.4}',
   '[{"section":"4.4","before":"A.","after":"B.","changes":[]}]', null, '2026-11-04 08:00+00'),
  ('00000000-0000-0000-0000-00000043c005', '00000000-0000-0000-0000-00000043p001',
   '00000000-0000-0000-0000-00000043s002', '00000000-0000-0000-0000-00000043s008', '{4.8}',
   '[{"section":"4.8","before":"Nausea.","after":"Nausea. Rash.","changes":[]}]', null, '2026-11-07 22:30+00');

-- ───────────── the reference product: one per ingredient, reviewers and administrators only ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.lc_refused($q$select set_reference_product('00000000-0000-0000-0000-00000043p001', true)$q$) as lc_reader_marks \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.lc_refused($q$select set_reference_product('00000000-0000-0000-0000-00000043ffff', true)$q$) as lc_unknown_product \gset
select set_reference_product('00000000-0000-0000-0000-00000043p002', true);
select set_reference_product('00000000-0000-0000-0000-00000043p001', true);    -- clears p002
reset role;
select pg_temp.lc_assert(:'lc_reader_marks' like '42501%', 'a reader cannot mark the reference product');
select pg_temp.lc_assert(:'lc_unknown_product' like 'P0002%', 'an unknown product cannot be marked');
select pg_temp.lc_assert(
  (select is_reference from spc_product where id = '00000000-0000-0000-0000-00000043p001')
  and not (select is_reference from spc_product where id = '00000000-0000-0000-0000-00000043p002')
  and (select count(*) from spc_product where ingredient_id = '00000000-0000-0000-0000-00000043a001' and is_reference) = 1,
  'marking one product as the reference clears the other product of the same ingredient');
select pg_temp.lc_assert(
  (select count(*) from audit_log where table_name = 'spc_product' and action = 'UPDATE'
      and new_row ->> 'is_reference' = 'true') = 2,
  'the reference mark is in the audit log');
select pg_temp.lc_refused($q$update spc_product set is_reference = true where id = '00000000-0000-0000-0000-00000043p002'$q$)
  as lc_two_refs \gset
select pg_temp.lc_assert(:'lc_two_refs' like '23505%', 'two reference products for one ingredient are refused by the table itself');

-- ───────────── our label, saved by the reviewer, and the gap the collector computed ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select save_our_label('00000000-0000-0000-0000-00000043a001', 'CI Labelamine 10 mg', 'Leaflet 2025', 'en',
  '{"4.4": "Use with caution in patients with renal impairment.", "4.8": "Nausea."}', 'leaflet-2025.pdf') as lc_label1 \gset
-- (a psql variable is not read inside dollar quotes, so the label is looked up)
select pg_temp.lc_refused($q$insert into label_gap (spc_change_id, our_label_id, gap)
  values ('00000000-0000-0000-0000-00000043c001',
          (select id from our_label where ingredient_id = '00000000-0000-0000-0000-00000043a001' and superseded_at is null),
          '{}')$q$) as lc_reviewer_writes_gap \gset
reset role;
-- the collector (owner connection) writes the gap
insert into label_gap (spc_change_id, our_label_id, gap) values
  ('00000000-0000-0000-0000-00000043c001', :'lc_label1',
   '{"lang_match": true, "our_lang": "en", "their_lang": "en", "covered": 0, "partly": 0, "missing": 1,'
   ' "sections": [{"section": "4.4", "our_section": "4.4", "our_text": true, "covered": 0, "partly": 0, "missing": 1,'
   ' "added": [{"sentence": "Cases of acute kidney injury have been reported.", "status": "missing", "score": 0, "closest": null}]}]}');
select pg_temp.lc_assert(:'lc_reviewer_writes_gap' like '42501%', 'only the collector writes label_gap');

-- ───────────── the decision on the originator's change ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000043e001', 'new', 'relevant', 'CI: our leaflet lacks it', my_person_id());

-- ───────────── label_changes(): the week Sun 1 – Sat 7 Nov 2026, Cairo ─────────────
select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')::text as lc_week \gset
select pg_temp.lc_refused($q$select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-07', '2026-11-01')$q$) as lc_backwards \gset
select pg_temp.lc_refused($q$select label_changes('00000000-0000-0000-0000-00000043a001', '2025-01-01', '2026-11-07')$q$) as lc_too_long \gset
select pg_temp.lc_refused($q$select label_changes('00000000-0000-0000-0000-00000043ffff', '2026-11-01', '2026-11-07')$q$) as lc_no_ingredient \gset
select label_changes('00000000-0000-0000-0000-00000043a001', '2026-12-01', '2026-12-07')::text as lc_quiet \gset
reset role;

select pg_temp.lc_assert(pg_temp.lc_ids(:'lc_week'::jsonb) = 'c001,c002',
  'the changes detected in the week, the reference product first, then newest first; the week before, the next '
  || 'Sunday 00:30 in Cairo and another ingredient are left out');
select pg_temp.lc_assert(:'lc_quiet' = '[]' and :'lc_backwards' like '22023%' and :'lc_too_long' like '22023%'
    and :'lc_no_ingredient' like 'P0002%',
  'no change gives an empty list; the days are checked as the Ingredients screen checks them');

select :'lc_week'::jsonb -> 0 as lc_c1 \gset
select :'lc_week'::jsonb -> 1 as lc_c2 \gset
select pg_temp.lc_assert(:'lc_c1'::jsonb ->> 'detected_day' = '2026-11-03'
    and (:'lc_c1'::jsonb ->> 'detected_at')::timestamptz = '2026-11-03 09:00+00'
    and :'lc_c1'::jsonb ->> 'label_date' = '2026-10-01'
    and :'lc_c1'::jsonb ->> 'previous_label_date' = '2026-06-01'
    and :'lc_c1'::jsonb ->> 'lang' = 'en'
    and :'lc_c1'::jsonb ->> 'title' = 'CI Labelamine Originator 10 mg — 4.4'
    and :'lc_c1'::jsonb ->> 'link' = 'https://label.example.test/products/1'
    and :'lc_c1'::jsonb ->> 'document_id' = '00000000-0000-0000-0000-00000043b001',
  'a change carries the day it was detected, the label''s date and the one before, the language, title and link');
select pg_temp.lc_assert(:'lc_c1'::jsonb -> 'product' ->> 'name' = 'CI Labelamine Originator 10 mg'
    and :'lc_c1'::jsonb -> 'product' ->> 'mah' = 'CI Originator Ltd'
    and :'lc_c1'::jsonb -> 'product' ->> 'country_code' = 'XL'
    and :'lc_c1'::jsonb -> 'product' ->> 'country_name' = 'CI Labelland'
    and :'lc_c1'::jsonb -> 'product' ->> 'regulator_name' = 'CI Labelland Agency'
    and :'lc_c1'::jsonb -> 'product' ->> 'source_id' = 'ci-lc-spc'
    and (:'lc_c1'::jsonb -> 'product' ->> 'is_reference')::boolean
    and not (:'lc_c2'::jsonb -> 'product' ->> 'is_reference')::boolean,
  'the product: name, holder, country, authority, source and whether it is the reference');
select pg_temp.lc_assert(:'lc_c1'::jsonb -> 'sections' = '["4.4"]'::jsonb
    and :'lc_c1'::jsonb -> 'diff' -> 0 ->> 'after' = 'Use with caution in renal impairment. Cases of acute kidney injury have been reported.'
    and :'lc_c1'::jsonb -> 'diff' -> 0 -> 'changes' -> 0 ->> 'op' = 'insert',
  'the sections and the stored word diff come as the label watch wrote them');
select pg_temp.lc_assert((:'lc_c1'::jsonb -> 'gap' ->> 'missing')::int = 1
    and :'lc_c1'::jsonb -> 'gap' -> 'sections' -> 0 -> 'added' -> 0 ->> 'status' = 'missing'
    and (:'lc_c1'::jsonb ->> 'gap_at') is not null
    and :'lc_c1'::jsonb -> 'our_label' ->> 'version' = 'Leaflet 2025'
    and :'lc_c1'::jsonb -> 'our_label' ->> 'product_name' = 'CI Labelamine 10 mg'
    and :'lc_c1'::jsonb -> 'our_label' ->> 'uploaded_by' = 'CI Reviewer'
    and :'lc_c1'::jsonb -> 'our_label' ->> 'id' = :'lc_label1',
  'the gap against our current label, and which label that is');
select pg_temp.lc_assert(:'lc_c1'::jsonb ->> 'issue_id' = '00000000-0000-0000-0000-00000043e001'
    and :'lc_c1'::jsonb ->> 'issue_status' = 'relevant'
    and :'lc_c1'::jsonb -> 'decision' ->> 'to_status' = 'relevant'
    and :'lc_c1'::jsonb -> 'decision' ->> 'person' = 'CI Admin'
    and :'lc_c1'::jsonb -> 'decision' ->> 'comment' = 'CI: our leaflet lacks it'
    and not (:'lc_c1'::jsonb ->> 'is_backfill')::boolean,
  'the notice, its status and the latest decision, as the Ingredients screen gives them');
select pg_temp.lc_assert(:'lc_c2'::jsonb -> 'gap' = 'null'::jsonb
    and :'lc_c2'::jsonb -> 'issue_id' = 'null'::jsonb
    and :'lc_c2'::jsonb -> 'decision' = 'null'::jsonb
    and :'lc_c2'::jsonb ->> 'issue_status' is null
    and :'lc_c2'::jsonb ->> 'link' = 'https://label.example.test/products'
    and :'lc_c2'::jsonb ->> 'title' = 'CI Labelamine Generic 10 mg — 10'
    and :'lc_c2'::jsonb -> 'our_label' ->> 'version' = 'Leaflet 2025'
    and :'lc_c2'::jsonb ->> 'lang' = 'en',
  'a change without a notice or a gap says so; with no page of its own the link is the source''s page');

-- ───────────── a new version of our label: the old comparison is not shown for it ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select save_our_label('00000000-0000-0000-0000-00000043a001', 'CI Labelamine 10 mg', 'Leaflet 2026', 'en',
  '{"4.4": "Use with caution in renal impairment. Cases of acute kidney injury have been reported."}') as lc_label2 \gset
select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')::text as lc_week2 \gset
reset role;
select pg_temp.lc_assert(:'lc_week2'::jsonb -> 0 -> 'gap' = 'null'::jsonb
    and :'lc_week2'::jsonb -> 0 -> 'our_label' ->> 'version' = 'Leaflet 2026'
    and :'lc_week2'::jsonb -> 0 -> 'our_label' ->> 'id' = :'lc_label2'
    and (select count(*) from label_gap where our_label_id = :'lc_label1') = 1,
  'a new version of our label has no comparison yet (the collector makes it); the old one is kept with the old label');

-- ───────────── who may read ─────────────
select set_config('request.jwt.claims', '', false);
select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')::text as lc_direct \gset
select pg_temp.lc_assert(pg_temp.lc_ids(:'lc_direct'::jsonb) = 'c001,c002',
  'the weekly report reads the label changes through its direct connection');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')::text as lc_reader \gset
select count(*) as lc_reader_gaps from label_gap where spc_change_id = '00000000-0000-0000-0000-00000043c001' \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.lc_refused($q$select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')$q$) as lc_stranger \gset
select coalesce(pg_temp.lc_refused($q$select count(*) from label_gap$q$), 'allowed') as lc_stranger_gaps \gset
reset role;
set role anon;
select pg_temp.lc_refused($q$select label_changes('00000000-0000-0000-0000-00000043a001', '2026-11-01', '2026-11-07')$q$) as lc_anon \gset
select pg_temp.lc_refused($q$select count(*) from label_gap$q$) as lc_anon_gaps \gset
select pg_temp.lc_refused($q$select set_reference_product('00000000-0000-0000-0000-00000043p001', false)$q$) as lc_anon_marks \gset
reset role;
select set_config('request.jwt.claims', '', false);
select pg_temp.lc_assert(pg_temp.lc_ids(:'lc_reader'::jsonb) = 'c001,c002' and :'lc_reader_gaps' = '1',
  'a reader on the team reads the label changes and the gaps');
select pg_temp.lc_assert(:'lc_stranger' like '42501%' and :'lc_anon' like '42501%' and :'lc_anon_gaps' like '42501%'
    and :'lc_anon_marks' like '42501%',
  'someone signed in but not on the team, and signed-out visitors, read and mark nothing');
select pg_temp.lc_assert(:'lc_stranger_gaps' = 'allowed' and (select count(*) from label_gap) > 0,
  'row-level security hides label_gap from a stranger');
select pg_temp.lc_assert(
  has_function_privilege('authenticated', 'public.label_changes(uuid, date, date)', 'execute')
    and has_function_privilege('authenticated', 'public.set_reference_product(uuid, boolean)', 'execute')
    and not has_function_privilege('anon', 'public.label_changes(uuid, date, date)', 'execute')
    and not has_function_privilege('anon', 'public.set_reference_product(uuid, boolean)', 'execute')
    and not has_table_privilege('authenticated', 'public.label_gap', 'insert')
    and not has_table_privilege('authenticated', 'public.label_gap', 'update')
    and not has_table_privilege('authenticated', 'public.label_gap', 'delete'),
  'the app calls label_changes and set_reference_product; label_gap is the collector''s to write');

rollback;
