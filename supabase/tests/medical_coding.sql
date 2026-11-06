-- PHAROS CI — medical coding (0061). Runs after every migration and the acceptance checks in ci.yml, on the same
-- database: the people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.

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

-- The words are compared as the coder compares them (collectors/coding/norm.py, tests/test_coding.py).
select pg_temp.ci_assert(coding_norm('  Hepatitis, Drug-Induced!! ') = 'hepatitis drug induced', 'ASCII punctuation and case');
select pg_temp.ci_assert(coding_norm('Ä Ödem') = 'Ä Ödem', 'letters beyond ASCII are kept as written');
select pg_temp.ci_assert(coding_norm('طفح جلدي، شديد') = 'طفح جلدي، شديد', 'Arabic is kept (its comma too)');
select pg_temp.ci_assert(coding_norm(null) = '', 'nothing is the empty string');

-- A trimmed MeSH: the body-system headings and three diseases.
insert into mesh_descriptor (ui, name, trees, scope_note) values
  ('D004066', 'Digestive System Diseases', '{C06}', null),
  ('D017437', 'Skin and Connective Tissue Diseases', '{C17}', null),
  ('D056486', 'Chemical and Drug Induced Liver Injury', '{C06.552.100,C25.100.468}', 'A spectrum of clinical liver diseases…'),
  ('D005076', 'Exanthema', '{C17.800.229,C23.888.885.250}', 'Diseases in which skin eruptions or rashes are a prominent manifestation.'),
  ('D009325', 'Nausea', '{C23.888.821.712}', null);
insert into mesh_term (ui, term, preferred) values
  ('D004066', 'Digestive System Diseases', true),
  ('D017437', 'Skin and Connective Tissue Diseases', true),
  ('D056486', 'Chemical and Drug Induced Liver Injury', true),
  ('D056486', 'Drug-Induced Liver Injury', false),
  ('D056486', 'Hepatitis, Drug-Induced', false),
  ('D056486', 'Hepatitis, Toxic', false),
  ('D005076', 'Exanthema', true),
  ('D005076', 'Rash', false),
  ('D005076', 'Skin Rash', false),
  ('D009325', 'Nausea', true);

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select ui from mesh_search('drug induced hepatitis') limit 1) = 'D056486',
                         'a reader finds liver injury from the words of the report');
select pg_temp.ci_assert((select ui from mesh_search('rash') limit 1) = 'D005076', 'an entry term finds its descriptor');
select pg_temp.ci_assert((select score from mesh_search('Skin Rash') limit 1) > 1, 'an exact name scores above any likeness');
select pg_temp.ci_assert((select count(*) from mesh_search('ra')) = 0, 'two letters are not a search');
select pg_temp.ci_assert((select categories from mesh_search('hepatitis toxic') limit 1)
                         = '{"Digestive System Diseases"}', 'the body system comes with the descriptor');
select pg_temp.ci_assert(pg_temp.refused($$insert into mesh_term (ui, term) values ('D009325', 'Sick')$$) like '42501%',
                         'nobody in the app writes the dictionary');
select pg_temp.ci_assert(pg_temp.refused($$select ask_case_coding('00000000-0000-0000-0000-00000061c001')$$) like '42501%',
                         'a reader cannot ask for coding');
reset role;

-- A confirmed case teaches the coder; a case still to confirm does not.
insert into safety_case (id, ref, origin, status, day_zero, r2_key, sha256, data) values
  ('00000000-0000-0000-0000-00000061c001', 'CASE-CI-0061-1', 'upload', 'confirmed', '2026-11-01', 'sha256/ci/1', 'ci1',
   '{"reactions":[{"verbatim":"Hepatitis toxic","english":"Toxic hepatitis","mesh_ui":"D056486",
                   "mesh_term":"Chemical and Drug Induced Liver Injury"}],
     "products":[{"name":"Carvid 25","active_ingredient":"carvedilol","rxcui":"20352","rxnorm_name":"carvedilol",
                  "indication":"Hypertension","indication_mesh_ui":"D006973","indication_mesh_term":"Hypertension"}]}'),
  ('00000000-0000-0000-0000-00000061c002', 'CASE-CI-0061-2', 'upload', 'to_confirm', '2026-11-02', 'sha256/ci/2', 'ci2',
   '{"reactions":[{"verbatim":"Hepatitis toxic","mesh_ui":"D005076","mesh_term":"Exanthema"}]}');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert((select code from coding_memory where kind = 'reaction' and norm = 'hepatitis toxic') = 'D056486',
                         'the confirmed case''s code is remembered, the unconfirmed one''s is not');
select pg_temp.ci_assert((select cases from coding_memory where kind = 'reaction' and norm = 'toxic hepatitis') = 1,
                         'the English words are remembered too');
select pg_temp.ci_assert((select code from coding_memory where kind = 'product' and norm = 'carvid 25') = '20352',
                         'a product''s RxNorm code is remembered under its name');
select pg_temp.ci_assert((select code from coding_memory where kind = 'indication' and norm = 'hypertension') = 'D006973',
                         'an indication is remembered');
reset role;
create temp table seen as select updated_at from safety_case where id = '00000000-0000-0000-0000-00000061c002';
grant select on seen to authenticated;
set role authenticated;
select ask_case_coding('00000000-0000-0000-0000-00000061c002');
reset role;
select pg_temp.ci_assert((select coding_status from safety_case where id = '00000000-0000-0000-0000-00000061c002') = 'queued',
                         'a reviewer asks for the codes again');
select pg_temp.ci_assert((select updated_at from safety_case where id = '00000000-0000-0000-0000-00000061c002')
                         = (select updated_at from seen), 'asking does not change the form''s version (no stale page)');

delete from safety_case where ref like 'CASE-CI-0061-%';
delete from mesh_descriptor;
