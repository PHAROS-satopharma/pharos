-- PHAROS CI — FDA adverse-event report counts (0071, 0076, 0078): ingredient_faers() with its quarters and the label tag, and who
-- may read and write them. Runs after every migration and the acceptance checks in ci.yml, on the same database: the
-- people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Everything here is rolled back.
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

-- A trimmed MeSH: a broader liver heading in our label, a rash in the reference label, nausea in neither.
delete from mesh_descriptor;
insert into mesh_descriptor (ui, name, trees, scope_note) values
  ('D008107', 'Liver Diseases', '{C06.552}', null),
  ('D006505', 'Hepatitis', '{C06.552.380}', null),
  ('D005076', 'Exanthema', '{C17.800.229}', null),
  ('D009325', 'Nausea', '{C23.888.821.712}', null);
insert into mesh_term (ui, term, preferred) values
  ('D008107', 'Liver Diseases', true),
  ('D006505', 'Hepatitis', true),
  ('D005076', 'Exanthema', true),
  ('D005076', 'Rash', false),
  ('D009325', 'Nausea', true);

insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000065a001', 'CI faersamine', 'Z99ZZ65'),
  ('00000000-0000-0000-0000-00000065a002', 'CI unlabelline', 'Z99ZZ66');

insert into label_coded (ingredient_id, source, label_ref, label_name, mesh_version, terms) values
  ('00000000-0000-0000-0000-00000065a001', 'our_label', 'ci-label', 'Faersamine 10 mg, March 2024', 'MeSH 2026', 1),
  ('00000000-0000-0000-0000-00000065a001', 'reference', 'ci-snap', 'Faersamin 10 mg', 'MeSH 2026', 1);
insert into label_mesh (ingredient_id, source, ui, term) values
  ('00000000-0000-0000-0000-00000065a001', 'our_label', 'D008107', 'liver disease'),
  ('00000000-0000-0000-0000-00000065a001', 'reference', 'D005076', 'rash');

-- What collectors/faers.py leaves: two quarters, the older with every reaction listed, the newer without.
insert into faers_ingredient (ingredient_id, searched, first_quarter, last_quarter, reports, all_reports) values
  ('00000000-0000-0000-0000-00000065a001', 'CI FAERSAMINE', '2026-04-01', '2026-07-01', 40, 600000),
  ('00000000-0000-0000-0000-00000065a002', 'CI UNLABELLINE', '2026-04-01', '2026-07-01', 9, 600000);
insert into faers_quarter (ingredient_id, quarter, reports, all_reports, complete) values
  ('00000000-0000-0000-0000-00000065a001', '2026-04-01', 15, 300000, true),
  ('00000000-0000-0000-0000-00000065a001', '2026-07-01', 25, 300000, false),
  ('00000000-0000-0000-0000-00000065a002', '2026-04-01', 4, 300000, true),
  ('00000000-0000-0000-0000-00000065a002', '2026-07-01', 5, 300000, true);
insert into faers_reaction (ingredient_id, reaction, reports, all_reports, prr, prr_low, prr_high, ror, ror_low,
                            ror_high, chi2, flagged) values
  ('00000000-0000-0000-0000-00000065a001', 'HEPATITIS', 12, 900, 200.0, 110.0, 360.0, 290.0, 140.0, 600.0, 2000.0, true),
  ('00000000-0000-0000-0000-00000065a001', 'NAUSEA', 9, 40000, 3.4, 1.8, 6.3, 4.6, 2.1, 9.9, 9.1, true),
  ('00000000-0000-0000-0000-00000065a001', 'RASH', 5, 30000, 2.5, 1.1, 5.8, 2.9, 1.1, 7.4, 3.0, false),
  ('00000000-0000-0000-0000-00000065a001', 'OFF LABEL USE', 5, 50000, 1.5, 0.6, 3.5, 1.6, 0.6, 3.9, 0.4, false),
  ('00000000-0000-0000-0000-00000065a002', 'NAUSEA', 2, 40000, 3.3, 0.9, 12.0, 3.6, 0.9, 14.0, 1.2, false);
insert into faers_count (ingredient_id, quarter, reaction, reports, all_reports) values
  ('00000000-0000-0000-0000-00000065a001', '2026-07-01', 'HEPATITIS', 12, 450),
  ('00000000-0000-0000-0000-00000065a001', '2026-04-01', 'NAUSEA', 9, 20000),
  ('00000000-0000-0000-0000-00000065a001', '2026-04-01', 'RASH', 2, 15000),
  ('00000000-0000-0000-0000-00000065a001', '2026-07-01', 'RASH', 3, null),
  ('00000000-0000-0000-0000-00000065a002', '2026-07-01', 'NAUSEA', 2, 20000);

update faers_reaction set co_drug = 'PARTNERINE', co_reports = 8, co_all_reports = 20
 where ingredient_id = '00000000-0000-0000-0000-00000065a001' and reaction = 'HEPATITIS';

-- Read as CI Reader; the temp table that keeps the answer is made by the owner.
create temp table f as select * from ingredient_faers(null) with no data;
create temp table g as select * from ingredient_faers(null) with no data;
grant select, insert on f, g to authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
insert into f select * from ingredient_faers('00000000-0000-0000-0000-00000065a001');
insert into g select * from ingredient_faers('00000000-0000-0000-0000-00000065a002');

select pg_temp.ci_assert((select array_agg(x.reaction) from ingredient_faers('00000000-0000-0000-0000-00000065a001') x)
                         = '{HEPATITIS,NAUSEA,"OFF LABEL USE",RASH}', 'the most reported first, then by name');
select pg_temp.ci_assert((select (quarters, last_quarter) = ('{0,12}'::int[], 12) from f where reaction = 'HEPATITIS'),
                         'a quarter with every reaction listed counts a missing reaction as none');
select pg_temp.ci_assert((select quarters = '{9,NULL}'::int[] and last_quarter is null from f where reaction = 'NAUSEA'),
                         'a quarter without every reaction listed leaves a missing one unknown');
select pg_temp.ci_assert((select quarters from f where reaction = 'RASH') = '{2,3}', 'the quarters, oldest first');
select pg_temp.ci_assert((select (prr, prr_low, prr_high, flagged, all_reports) = (200.0, 110.0, 360.0, true, 900)
                            from f where reaction = 'HEPATITIS'), 'the disproportion is given as the collector kept it');
select pg_temp.ci_assert((select (co_drug, co_reports, co_all_reports) = ('PARTNERINE', 8, 20)
                            from f where reaction = 'HEPATITIS')
                         and (select co_drug is null and co_reports is null and co_all_reports is null
                                from f where reaction = 'NAUSEA'),
                         'the drug over-represented with a flagged reaction is given as the collector kept it (0078)');
select pg_temp.ci_assert((select (mesh_ui, listed) = ('D006505', 'our_label') from f where reaction = 'HEPATITIS'),
                         'HEPATITIS is MeSH Hepatitis, under the liver heading our label names');
select pg_temp.ci_assert((select (mesh_ui, listed) = ('D005076', 'reference') from f where reaction = 'RASH'),
                         'RASH matches a MeSH entry name, and the reference label lists it');
select pg_temp.ci_assert((select (mesh_ui, listed) = ('D009325', 'not_listed') from f where reaction = 'NAUSEA'),
                         'nausea is in neither label');
select pg_temp.ci_assert((select mesh_ui is null and listed is null from f where reaction = 'OFF LABEL USE'),
                         'a name MeSH does not have is unknown, never "not in our label"');
select pg_temp.ci_assert((select mesh_ui = 'D009325' and listed is null from g),
                         'without a coded label the tag is unknown');

select pg_temp.ci_assert((select count(*) from faers_ingredient where searched like 'CI %') = 2,
                         'a member of the team reads what was fetched');
select pg_temp.ci_assert(pg_temp.refused($$insert into faers_reaction (ingredient_id, reaction, reports, all_reports,
  flagged) values ('00000000-0000-0000-0000-00000065a002', 'HEADACHE', 1, 1, false)$$) like '42501%',
                         'nobody in the app writes the counts');
select pg_temp.refused($$update faers_ingredient set reports = 0$$);
select pg_temp.refused($$delete from faers_count$$);
select pg_temp.ci_assert((select sum(reports) from faers_ingredient where searched like 'CI %') = 49
                         and (select count(*) from faers_count where reaction = 'RASH') = 2,
                         'an update or a delete from the app changes nothing');

-- Signed in, but not a member of the team.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-00000065ffff","role":"authenticated"}', false);
select pg_temp.ci_assert(pg_temp.refused($$select * from ingredient_faers('00000000-0000-0000-0000-00000065a001')$$)
                         like '42501%', 'only a member of the team reads the counts');
select pg_temp.ci_assert((select count(*) from faers_reaction) = 0, 'nor the tables');
reset role;

select pg_temp.ci_assert((select prosecdef from pg_proc where proname = 'ingredient_faers'),
                         'the counts run as their owner, the role checked once');

set role anon;
select pg_temp.ci_assert(pg_temp.refused($$select * from ingredient_faers('00000000-0000-0000-0000-00000065a001')$$)
                         like '42501%', 'nobody signed out reads the counts');
reset role;

-- Removing an ingredient removes its counts.
delete from ingredient where id = '00000000-0000-0000-0000-00000065a002';
select pg_temp.ci_assert(not exists (select 1 from faers_count where ingredient_id = '00000000-0000-0000-0000-00000065a002'),
                         'the counts go with their ingredient');

rollback;
