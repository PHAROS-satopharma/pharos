-- PHAROS CI — what the coded terms say (0062): counts per MeSH term and per safety topic, and which label lists
-- a reaction. Runs after every migration and the acceptance checks in ci.yml, on the same database: the people
-- CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Everything here is rolled back.
begin;

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

select pg_temp.ci_assert((select count(*) from safety_topic) = 31, 'the 31 safety topics are seeded');

-- A trimmed MeSH: a broader liver heading, the diseases counted, and two that must not be.
delete from mesh_descriptor;
insert into mesh_descriptor (ui, name, trees, scope_note) values
  ('D008107', 'Liver Diseases', '{C06.552}', null),
  ('D056486', 'Chemical and Drug Induced Liver Injury', '{C06.552.100,C25.100.468}', null),
  ('D006505', 'Hepatitis', '{C06.552.380}', null),
  ('D005076', 'Exanthema', '{C17.800.229}', null),
  ('D009325', 'Nausea', '{C23.888.821.712}', null),
  ('D012640', 'Seizures', '{C10.597.742}', null),
  ('D016728', 'Suicide', '{F01.145.126.980.875}', null);

insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000062a001', 'CI codamine', 'Z99ZZ62');

-- The labels as collectors/coding/labels.py leaves them: ours names "liver disease", the reference names a rash.
insert into label_coded (ingredient_id, source, label_ref, label_name, mesh_version, terms) values
  ('00000000-0000-0000-0000-00000062a001', 'our_label', 'ci-label', 'Codamine 10 mg, March 2024', 'MeSH 2026', 1),
  ('00000000-0000-0000-0000-00000062a001', 'reference', 'ci-snap', 'Codamin 10 mg', 'MeSH 2026', 2);
insert into label_mesh (ingredient_id, source, ui, term) values
  ('00000000-0000-0000-0000-00000062a001', 'our_label', 'D008107', 'liver disease'),
  ('00000000-0000-0000-0000-00000062a001', 'reference', 'D005076', 'rash'),
  ('00000000-0000-0000-0000-00000062a001', 'reference', 'D008107', 'hepatic disorder');

-- Cases: one this month (liver injury, nausea), one the month before (liver injury), one not valid (not counted).
insert into safety_case (id, ref, origin, status, day_zero, r2_key, sha256, ingredient_id, data) values
  ('00000000-0000-0000-0000-00000062c001', 'CASE-CI-0062-1', 'upload', 'confirmed', '2026-11-01', 'sha256/ci/62-1',
   'ci62-1', '00000000-0000-0000-0000-00000062a001',
   '{"reactions":[{"verbatim":"toxic hepatitis","mesh_ui":"D056486"},{"verbatim":"nausea","mesh_ui":"D009325"},
                  {"verbatim":"not coded yet"}]}'),
  ('00000000-0000-0000-0000-00000062c002', 'CASE-CI-0062-2', 'upload', 'to_confirm', '2026-10-05', 'sha256/ci/62-2',
   'ci62-2', '00000000-0000-0000-0000-00000062a001', '{"reactions":[{"verbatim":"DILI","mesh_ui":"D056486"}]}'),
  ('00000000-0000-0000-0000-00000062c003', 'CASE-CI-0062-3', 'upload', 'not_valid', '2026-11-02', 'sha256/ci/62-3',
   'ci62-3', '00000000-0000-0000-0000-00000062a001', '{"reactions":[{"verbatim":"nausea","mesh_ui":"D009325"}]}');

-- Papers: p1 this month reports a rash ("chemically induced") and names seizures without the qualifier; p2 the
-- month before reports liver injury (a C25 heading); p3 reports suicide but is only a suggested link.
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-CS-N', 'XN', 'CI Paperland', 'CI Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-cs-lit', 'CI-CS-N', 'literature', 'api', 'https://papers.example.test/', 'ci', '{en}', null, true);
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-00000062d001', 'ci-cs-lit', '62001', 'https://papers.example.test/62001',
   'Rash with codamine', 'en', 'literature', '2026-10-20', '2026-10-21 08:00+00', false,
   '{"pmid":"62001","mesh":[{"ui":"D005076","name":"Exanthema","major":true,"q":["Q000139"]},
                            {"ui":"D012640","name":"Seizures","major":false,"q":[]}]}'),
  ('00000000-0000-0000-0000-00000062d002', 'ci-cs-lit', '62002', 'https://papers.example.test/62002',
   'Liver injury with codamine', 'en', 'literature', null, '2026-09-15 08:00+00', false,
   '{"pmid":"62002","mesh":[{"ui":"D056486","name":"Chemical and Drug Induced Liver Injury","major":true,"q":[]}]}'),
  ('00000000-0000-0000-0000-00000062d003', 'ci-cs-lit', '62003', 'https://papers.example.test/62003',
   'Suicide and something else', 'en', 'literature', '2026-10-25', '2026-10-25 08:00+00', false,
   '{"pmid":"62003","mesh":[{"ui":"D016728","name":"Suicide","major":true,"q":["Q000139"]}]}');
insert into issue (id, doc_type, title, anchor_document_id, first_date, is_backfill, class_only) values
  ('00000000-0000-0000-0000-00000062e001', 'literature', 'Rash with codamine',
   '00000000-0000-0000-0000-00000062d001', '2026-10-20', false, false),
  ('00000000-0000-0000-0000-00000062e002', 'literature', 'Liver injury with codamine',
   '00000000-0000-0000-0000-00000062d002', '2026-09-15', false, false),
  ('00000000-0000-0000-0000-00000062e003', 'literature', 'Suicide and something else', null, null, false, false);
insert into issue_ingredient (issue_id, ingredient_id) values
  ('00000000-0000-0000-0000-00000062e001', '00000000-0000-0000-0000-00000062a001'),
  ('00000000-0000-0000-0000-00000062e002', '00000000-0000-0000-0000-00000062a001'),
  ('00000000-0000-0000-0000-00000062e003', '00000000-0000-0000-0000-00000062a001');
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000062e001', '00000000-0000-0000-0000-00000062d001', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000062e002', '00000000-0000-0000-0000-00000062d002', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000062e003', '00000000-0000-0000-0000-00000062d003', 'copy', 'suggested');

-- The counts are read as CI Reader; the temp tables that keep them are made by the owner.
create temp table m as select * from ingredient_mesh_counts(null, null, null) with no data;
create temp table t as select * from ingredient_topic_counts(null, null, null) with no data;
grant select, insert on m, t to authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
insert into m select * from ingredient_mesh_counts('00000000-0000-0000-0000-00000062a001', '2026-10-08', '2026-11-06');
select pg_temp.ci_assert((select array_agg(ui order by ui) from m) = '{D005076,D009325,D056486}',
                         'only reactions are counted: no heading without "chemically induced", no suggested link');
select pg_temp.ci_assert((select (cases_now, cases_before, papers_now, papers_before) = (1, 1, 0, 1) from m
                           where ui = 'D056486'), 'liver injury: a case now, a case and a paper the month before');
select pg_temp.ci_assert((select cases_now from m where ui = 'D009325') = 1, 'a case not valid is not counted');
select pg_temp.ci_assert((select papers_now from m where ui = 'D005076') = 1, 'a paper is dated by its publication');
select pg_temp.ci_assert((select listed from m where ui = 'D056486') = 'our_label',
                         'a broader heading in our label lists the reaction, and our label comes first');
select pg_temp.ci_assert((select listed from m where ui = 'D005076') = 'reference', 'the reference label lists a rash');
select pg_temp.ci_assert((select listed from m where ui = 'D009325') is null, 'nausea is in neither label');

insert into t select * from ingredient_topic_counts('00000000-0000-0000-0000-00000062a001', '2026-10-08', '2026-11-06');
select pg_temp.ci_assert((select array_agg(topic) from t) = '{liver}', 'only the liver topic has reports');
select pg_temp.ci_assert((select (cases_now, cases_before, papers_now, papers_before) = (1, 1, 0, 1) from t),
                         'a topic counts the descriptors beneath its seeds');
select pg_temp.ci_assert((select terms from t) = '{"Chemical and Drug Induced Liver Injury"}',
                         'the topic names the terms it found');
select pg_temp.ci_assert((select array_agg(ui order by ui) from topic_descriptor where topic_id = 'liver')
                         = '{D006505,D056486}', 'the liver topic holds the seeds MeSH has, not their parent');
select pg_temp.ci_assert(pg_temp.refused($$insert into label_mesh (ingredient_id, source, ui, term)
  values ('00000000-0000-0000-0000-00000062a001', 'our_label', 'D009325', 'nausea')$$) like '42501%',
                         'nobody in the app writes the label terms');
select pg_temp.ci_assert(pg_temp.refused($$insert into safety_topic (id, name, uis) values ('x', 'X', '{D009325}')$$)
                         like '42501%', 'nobody in the app writes the topics');
reset role;

set role anon;
select pg_temp.ci_assert(pg_temp.refused($$select * from ingredient_mesh_counts('00000000-0000-0000-0000-00000062a001',
  '2026-10-08', '2026-11-06')$$) like '42501%', 'nobody signed out counts');
reset role;

rollback;
