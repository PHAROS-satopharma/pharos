-- PHAROS CI — the Japan code of an ingredient that already exists (0052): set_japan_code(). Runs on the database
-- ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Everything here happens in one
-- transaction that is rolled back at the end, so nothing is left behind.
--
-- The code is PMDA's 一般名 code: levofloxacin hydrate's is 6241013, whose page
-- https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/6241013 lists Cravit and its generics. The test never
-- reads PMDA; the ingredients below are CI rows, not the watchlist's.

begin;

create function pg_temp.jc_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.jc_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- An ingredient already on the watchlist with its names and no Japan code, and another one with its own code.
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000051a001', 'ci-levofloxacin', 'J01MA12'),
  ('00000000-0000-0000-0000-00000051a002', 'ci-lornoxicam', 'M01AC05');
insert into ingredient_term (id, ingredient_id, lang, country_code, term, kind, mode, source) values
  ('00000000-0000-0000-0000-00000051b001', '00000000-0000-0000-0000-00000051a001', 'en', null, 'levofloxacin', 'inn', 'stem', 'wikidata'),
  ('00000000-0000-0000-0000-00000051b002', '00000000-0000-0000-0000-00000051a001', 'ja', null, 'レボフロキサシン', 'inn', 'substring', 'wikidata'),
  ('00000000-0000-0000-0000-00000051b003', '00000000-0000-0000-0000-00000051a001', 'ja', 'JP', 'クラビット', 'brand', 'substring', 'manual'),
  ('00000000-0000-0000-0000-00000051b004', '00000000-0000-0000-0000-00000051a002', 'ja', 'JP', '1149036', 'code', 'exact', 'pmda');
update ingredient_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00'
 where ingredient_id in ('00000000-0000-0000-0000-00000051a001', '00000000-0000-0000-0000-00000051a002');

create temp table jc_before as
  select id, term, kind, mode, lang, country_code, changed_at from ingredient_term
   where id in ('00000000-0000-0000-0000-00000051b001', '00000000-0000-0000-0000-00000051b002',
                '00000000-0000-0000-0000-00000051b003', '00000000-0000-0000-0000-00000051b004');
grant select on jc_before to authenticated;

-- ───────────── who may set it: an administrator, as save_ingredient and the term policy allow ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', '6241013')$q$) as jc_reader \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', '6241013')$q$) as jc_reviewer \gset
reset role;
select pg_temp.jc_assert(:'jc_reader' like '42501%', 'a reader cannot set a Japan code');
select pg_temp.jc_assert(:'jc_reviewer' like '42501%', 'a reviewer cannot set a Japan code (the names are an administrator''s)');
select pg_temp.jc_assert(
  not exists (select 1 from ingredient_term where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code'),
  'a refused call leaves no code behind');
select pg_temp.jc_assert(
  not has_function_privilege('anon', 'public.set_japan_code(uuid, text)', 'execute')
    and has_function_privilege('authenticated', 'public.set_japan_code(uuid, text)', 'execute'),
  'signed-out visitors cannot call it; the team can (the function itself asks for an administrator)');

-- ───────────── what it accepts: isJapanCode's rule (readiness.ts) ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', 'J01MA12')$q$) as jc_atc \gset
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', '624101')$q$) as jc_short \gset
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', '62410130')$q$) as jc_eight \gset
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', '')$q$) as jc_empty \gset
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-00000051a001', null)$q$) as jc_null \gset
select pg_temp.jc_refused($q$select set_japan_code('00000000-0000-0000-0000-0000005100ff', '6241013')$q$) as jc_unknown \gset
reset role;
select pg_temp.jc_assert(:'jc_atc' like '22023%' and :'jc_atc' like '%7 characters%', 'an ATC code is refused, saying what a Japan code looks like');
select pg_temp.jc_assert(:'jc_short' like '22023%', 'six characters are refused');
select pg_temp.jc_assert(:'jc_eight' like '22023%', 'eight characters are refused');
select pg_temp.jc_assert(:'jc_empty' like '22023%' and :'jc_null' like '22023%', 'nothing is refused');
select pg_temp.jc_assert(:'jc_unknown' like 'P0002%', 'an ingredient not on the watchlist is refused');

-- ───────────── the first code: a YJ code is stored as the 7 characters it starts with ─────────────
set role authenticated;
select set_japan_code('00000000-0000-0000-0000-00000051a001', ' 6241013f1020 ') as jc_saved \gset
reset role;
select pg_temp.jc_assert(:'jc_saved' = '6241013', 'it answers the code it stored');
select pg_temp.jc_assert(
  (select count(*) = 1
          and bool_and(term = '6241013' and lang = 'ja' and kind = 'code' and mode = 'exact' and source = 'pmda')
          and bool_and(verified_by = (select id from person where email = 'admin@example.test') and verified_at is not null)
     from ingredient_term
    where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code' and country_code = 'JP'),
  'the 12-character YJ code, in any case and with spaces, is stored as its 7-character code, exact, from PMDA, verified by the administrator');
select pg_temp.jc_assert(
  (select changed_at > '2026-01-02 00:00+00' and rematched_at is null from ingredient_term
    where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code'),
  'the new code is due for the check of the past (0034 changed_at), as every new word is');
select pg_temp.jc_assert(
  (select count(*) = 4 from ingredient_term t join jc_before b using (id)
    where t.term = b.term and t.kind = b.kind and t.mode = b.mode and t.lang = b.lang
      and t.country_code is not distinct from b.country_code and t.changed_at = b.changed_at),
  'its names, its Japanese brand and the other ingredient''s code are untouched');
select pg_temp.jc_assert(
  (ingredient_readiness('00000000-0000-0000-0000-00000051a001') -> 'label_watch' ->> 'japan_code')::boolean,
  'the readiness line now knows the Japan code');
select pg_temp.jc_assert(
  exists (select 1 from audit_log where table_name = 'ingredient_term' and action = 'INSERT'
            and new_row ->> 'term' = '6241013' and actor = '00000000-0000-0000-0000-0000000000a1'),
  'the new code is in the audit log, by the administrator who set it');

-- ───────────── saving the same code again changes nothing that the past check reads ─────────────
update ingredient_term set rematched_at = changed_at
 where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code';
create temp table jc_first as
  select id, changed_at from ingredient_term where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code';
grant select on jc_first to authenticated;
set role authenticated;
select set_japan_code('00000000-0000-0000-0000-00000051a001', '6241013') as jc_again \gset
reset role;
select pg_temp.jc_assert(
  (select count(*) = 1 from ingredient_term t join jc_first f using (id)
    where t.changed_at = f.changed_at and t.rematched_at = f.changed_at)
  and (select count(*) = 1 from ingredient_term
        where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code'),
  'the same code again keeps its row and is not due again');

-- ───────────── a different code replaces it; nothing else moves ─────────────
set role authenticated;
select set_japan_code('00000000-0000-0000-0000-00000051a001', '6241400') as jc_replaced \gset
reset role;
select pg_temp.jc_assert(
  (select array_agg(term) = '{6241400}' from ingredient_term
    where ingredient_id = '00000000-0000-0000-0000-00000051a001' and kind = 'code' and country_code = 'JP'),
  'a new code replaces the previous one: one Japan code per ingredient');
select pg_temp.jc_assert(
  exists (select 1 from audit_log where table_name = 'ingredient_term' and action = 'DELETE'
            and old_row ->> 'term' = '6241013' and actor = '00000000-0000-0000-0000-0000000000a1'),
  'the code it replaced is in the audit log as removed, by the administrator');
select pg_temp.jc_assert(
  (select count(*) = 4 from ingredient_term t join jc_before b using (id)
    where t.term = b.term and t.kind = b.kind and t.changed_at = b.changed_at),
  'replacing it leaves every other term alone, the other ingredient''s code included');

rollback;
