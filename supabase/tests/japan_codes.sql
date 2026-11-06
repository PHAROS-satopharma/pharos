-- PHAROS CI — several Japan codes for one ingredient (0069): set_japan_codes(). Runs on the database ci.yml
-- prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Everything here happens in one transaction
-- that is rolled back at the end, so nothing is left behind.
--
-- PMDA files one ingredient under one 一般名 code per form: paracetamol (アセトアミノフェン) is 1141007 for the tablets
-- and powders, 1141700 for the suppositories and 1141400 for the injection (GeneralList pages read 6 Nov 2026). With
-- one code per ingredient (0052) Japan's label watch saw the tablets only. The test never reads PMDA; the
-- ingredients below are CI rows without an ATC code, so no seed or other test collides with them.

begin;

create function pg_temp.jm_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.jm_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

create function pg_temp.jm_codes(p uuid) returns text[] language sql as $$
  select coalesce(array_agg(term order by term), '{}') from ingredient_term
   where ingredient_id = p and kind = 'code' and country_code = 'JP'
$$;

-- Paracetamol with its tablet code and its names; another ingredient with its own code.
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000069a001', 'ci-jm-paracetamol', null),
  ('00000000-0000-0000-0000-00000069a002', 'ci-jm-lornoxicam', null);
insert into ingredient_term (id, ingredient_id, lang, country_code, term, kind, mode, source) values
  ('00000000-0000-0000-0000-00000069b001', '00000000-0000-0000-0000-00000069a001', 'en', null, 'paracetamol', 'inn', 'stem', 'wikidata'),
  ('00000000-0000-0000-0000-00000069b002', '00000000-0000-0000-0000-00000069a001', 'ja', null, 'アセトアミノフェン', 'inn', 'substring', 'wikidata'),
  ('00000000-0000-0000-0000-00000069b003', '00000000-0000-0000-0000-00000069a001', 'ja', 'JP', '1141007', 'code', 'exact', 'pmda'),
  ('00000000-0000-0000-0000-00000069b004', '00000000-0000-0000-0000-00000069a002', 'ja', 'JP', '1149036', 'code', 'exact', 'pmda');
update ingredient_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00'
 where ingredient_id in ('00000000-0000-0000-0000-00000069a001', '00000000-0000-0000-0000-00000069a002');

create temp table jm_names as
  select id, term, kind, changed_at from ingredient_term
   where id in ('00000000-0000-0000-0000-00000069b001', '00000000-0000-0000-0000-00000069b002',
                '00000000-0000-0000-0000-00000069b004');
grant select on jm_names to authenticated;

-- ───────────── who may set them: an administrator only ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', array['1141007','1141700'])$q$) as jm_reader \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', array['1141007','1141700'])$q$) as jm_reviewer \gset
reset role;
select pg_temp.jm_assert(:'jm_reader' like '42501%' and :'jm_reviewer' like '42501%',
  'a reader and a reviewer cannot set Japan codes');
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a001') = '{1141007}',
  'a refused call changes no code');
select pg_temp.jm_assert(
  not has_function_privilege('anon', 'public.set_japan_codes(uuid, text[])', 'execute')
    and has_function_privilege('authenticated', 'public.set_japan_codes(uuid, text[])', 'execute'),
  'signed-out visitors cannot call it; the team can (the function itself asks for an administrator)');

-- ───────────── what it accepts: every code by isJapanCode's rule, at least one ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', array['1141700','N02BE01'])$q$) as jm_one_bad \gset
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', array[]::text[])$q$) as jm_none \gset
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', array['  ', null])$q$) as jm_blank \gset
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-00000069a001', null)$q$) as jm_null \gset
select pg_temp.jm_refused($q$select set_japan_codes('00000000-0000-0000-0000-0000006900ff', array['1141007'])$q$) as jm_unknown \gset
reset role;
select pg_temp.jm_assert(:'jm_one_bad' like '22023%' and :'jm_one_bad' like '%N02BE01%',
  'one wrong code refuses the whole list, naming it');
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a001') = '{1141007}',
  'a refused list leaves the codes as they were');
select pg_temp.jm_assert(:'jm_none' like '22023%' and :'jm_blank' like '22023%' and :'jm_null' like '22023%',
  'an empty list is refused: it would remove every code');
select pg_temp.jm_assert(:'jm_unknown' like 'P0002%', 'an ingredient not on the watchlist is refused');

-- ───────────── more codes: the one it had stays, the new ones join it ─────────────
set role authenticated;
select set_japan_codes('00000000-0000-0000-0000-00000069a001',
                       array['1141007', ' 1141700j1029 ', '1141400', '1141007F1063']) as jm_saved \gset
reset role;
select pg_temp.jm_assert(:'jm_saved' = '{1141007,1141400,1141700}',
  'it answers the codes it stored, each once, in order');
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a001') = '{1141007,1141400,1141700}',
  'three Japan codes for one ingredient: YJ codes stored as their 7 characters, a repeat stored once');
select pg_temp.jm_assert(
  (select bool_and(lang = 'ja' and mode = 'exact' and source = 'pmda' and verified_at is not null
                   and verified_by = (select id from person where email = 'admin@example.test'))
     from ingredient_term where ingredient_id = '00000000-0000-0000-0000-00000069a001' and kind = 'code'),
  'each is exact, from PMDA, verified by the administrator');
select pg_temp.jm_assert(
  (select changed_at = '2026-01-01 00:00+00' and rematched_at = '2026-01-01 00:00+00' from ingredient_term
    where id = '00000000-0000-0000-0000-00000069b003'),
  'the code it already had keeps its row and is not due for the check of the past again');
select pg_temp.jm_assert(
  (select count(*) = 2 and bool_and(changed_at > '2026-01-02 00:00+00' and rematched_at is null) from ingredient_term
    where ingredient_id = '00000000-0000-0000-0000-00000069a001' and kind = 'code'
      and id <> '00000000-0000-0000-0000-00000069b003'),
  'the two new codes are due for the check of the past (0034 changed_at)');
select pg_temp.jm_assert(
  (select count(*) = 2 from audit_log where table_name = 'ingredient_term' and action = 'INSERT'
     and new_row ->> 'term' in ('1141700', '1141400') and actor = '00000000-0000-0000-0000-0000000000a1'),
  'each new code is in the audit log, by the administrator');
select pg_temp.jm_assert(
  (select count(*) = 3 from ingredient_term t join jm_names n using (id)
    where t.term = n.term and t.kind = n.kind and t.changed_at = n.changed_at),
  'its names and the other ingredient''s code are untouched');
select pg_temp.jm_assert(
  (ingredient_readiness('00000000-0000-0000-0000-00000069a001') -> 'label_watch' ->> 'japan_code')::boolean,
  'the readiness line still knows it has a Japan code');

-- ───────────── a code left off the list goes; nothing else moves ─────────────
set role authenticated;
select set_japan_codes('00000000-0000-0000-0000-00000069a001', array['1141007', '1141700']) as jm_fewer \gset
reset role;
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a001') = '{1141007,1141700}',
  'the code left off the list is removed, the others stay');
select pg_temp.jm_assert(
  exists (select 1 from audit_log where table_name = 'ingredient_term' and action = 'DELETE'
            and old_row ->> 'term' = '1141400' and actor = '00000000-0000-0000-0000-0000000000a1'),
  'the removed code is in the audit log as removed, by the administrator');
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a002') = '{1149036}',
  'the other ingredient keeps its code');

-- ───────────── the single-code call (0052) still replaces every code with one ─────────────
set role authenticated;
select set_japan_code('00000000-0000-0000-0000-00000069a001', '1141007') as jm_single \gset
reset role;
select pg_temp.jm_assert(pg_temp.jm_codes('00000000-0000-0000-0000-00000069a001') = '{1141007}',
  'set_japan_code keeps its meaning: the one code given, the others removed');

rollback;
