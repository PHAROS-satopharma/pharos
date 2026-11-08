-- PHAROS CI — an administrator removes an ingredient or a source she added (0100). Runs on the database ci.yml
-- prepared: CI Admin (…a1), CI Reader (…b2) and CI Admin Two (…d4) exist. CI Admin Two plays the QPPV: an
-- administrator who does not manage the people (0053). One transaction, rolled back at the end.

begin;

create function pg_temp.rm_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- What the database refuses, as its SQLSTATE (null when it was accepted).
create function pg_temp.rm_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate;
end $$;

update person set manages_people = false where auth_user_id = '00000000-0000-0000-0000-0000000000d4';

-- A misspelt ingredient added just now, with only its names; one with a notice linked; one in a product; one added
-- two days ago and screened since (a run yesterday), with nothing found.
insert into ingredient (id, inn_en) values
  ('00000000-0000-0000-0000-000000100a01', 'CI carvedilolx'),
  ('00000000-0000-0000-0000-000000100a02', 'CI linkoxicam'),
  ('00000000-0000-0000-0000-000000100a03', 'CI prodoxicam');
insert into ingredient (id, inn_en, created_at) values
  ('00000000-0000-0000-0000-000000100a04', 'CI oldoxicam', '2026-11-06 10:00+02');
insert into ingredient_term (ingredient_id, term, lang, kind) values
  ('00000000-0000-0000-0000-000000100a01', 'ci carvedilolx', 'en', 'inn');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-RM', 'XR', 'CI Removeland', 'CI Remove Agency', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, enabled, origin) values
  ('ci-rm-catalogue', 'CI-RM', 'safety', 'rss', 'https://rm.example.test/feed', 'feed', '{en}', true, 'catalogue'),
  ('user-ci-rm-empty', 'CI-RM', 'safety', 'rss', 'https://rm.example.test/empty', 'feed', '{en}', true, 'user'),
  ('user-ci-rm-found', 'CI-RM', 'safety', 'rss', 'https://rm.example.test/found', 'feed', '{en}', true, 'user'),
  ('user-ci-rm-never', 'CI-RM', 'safety', 'rss', 'https://rm.example.test/never', 'feed', '{en}', true, 'user');
-- A run before this test's ingredients were added (now() is the transaction's start), after CI oldoxicam was.
insert into run (id, trigger, started_at) values ('00000000-0000-0000-0000-000000100c01', 'manual', now() - interval '1 day');
insert into source_run (run_id, source_id) values ('00000000-0000-0000-0000-000000100c01', 'user-ci-rm-empty');
insert into document (id, source_id, external_id, url, title_orig) values
  ('00000000-0000-0000-0000-000000100b01', 'user-ci-rm-found', 'rm1', 'https://rm.example.test/1', 'CI linkoxicam notice');
insert into match (document_id, ingredient_id, field, matched_text) values
  ('00000000-0000-0000-0000-000000100b01', '00000000-0000-0000-0000-000000100a02', 'title', 'CI linkoxicam');
insert into product (id, name) values ('00000000-0000-0000-0000-000000100d01', 'CI Prodexa');
insert into product_ingredient (product_id, ingredient_id) values
  ('00000000-0000-0000-0000-000000100d01', '00000000-0000-0000-0000-000000100a03');

-- ───────────── a reader can remove nothing ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.rm_refused($$select remove_ingredient('00000000-0000-0000-0000-000000100a01')$$) as rm_r_ing,
       pg_temp.rm_refused($$select remove_source('user-ci-rm-empty')$$) as rm_r_src \gset
reset role;
select pg_temp.rm_assert(:'rm_r_ing' = '42501', 'a reader cannot remove an ingredient');
select pg_temp.rm_assert(:'rm_r_src' = '42501', 'a reader cannot remove a source');
select pg_temp.rm_assert((select count(*) = 4 from ingredient where id::text like '00000000-0000-0000-0000-000000100a0%'),
  'every ingredient is still there');

-- ───────────── the QPPV, an administrator without the People screen ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000d4","role":"authenticated"}', false);
set role authenticated;
select not i_manage_people() as rm_q_not_people \gset
select remove_ingredient('00000000-0000-0000-0000-000000100a01') as rm_q_ing1,
       remove_ingredient('00000000-0000-0000-0000-000000100a02') as rm_q_ing2,
       remove_ingredient('00000000-0000-0000-0000-000000100a03') as rm_q_ing3,
       remove_ingredient('00000000-0000-0000-0000-000000100a04') as rm_q_ing4 \gset
select pg_temp.rm_refused($$select remove_source('ci-rm-catalogue')$$) as rm_q_cat \gset
select remove_source('user-ci-rm-empty') as rm_q_src1, remove_source('user-ci-rm-found') as rm_q_src2,
       remove_source('user-ci-rm-never') as rm_q_src3 \gset
-- The two functions are the only way to delete: an administrator's direct delete is refused.
select pg_temp.rm_refused($$delete from source where id = 'user-ci-rm-found'$$) as rm_q_direct_src,
       pg_temp.rm_refused($$delete from ingredient where id = '00000000-0000-0000-0000-000000100a02'$$) as rm_q_direct_ing \gset
select pg_temp.rm_refused($$select remove_ingredient('00000000-0000-0000-0000-000000100a01')$$) as rm_q_again \gset
reset role;

select pg_temp.rm_assert(:'rm_q_not_people', 'she does not manage the people');

select pg_temp.rm_assert((:'rm_q_ing1')::jsonb ->> 'outcome' = 'deleted', 'an ingredient with nothing recorded is deleted');
select pg_temp.rm_assert(not exists (select 1 from ingredient where id = '00000000-0000-0000-0000-000000100a01'),
  'the deleted ingredient is gone');
select pg_temp.rm_assert(not exists (select 1 from ingredient_term where ingredient_id = '00000000-0000-0000-0000-000000100a01'),
  'its names went with it');
select pg_temp.rm_assert(:'rm_q_again' = 'P0002', 'removing it again says it is not on the list');

select pg_temp.rm_assert((:'rm_q_ing2')::jsonb ->> 'outcome' = 'paused', 'an ingredient with a linked notice is paused');
select pg_temp.rm_assert((:'rm_q_ing2')::jsonb -> 'reasons' = '["1 notice linked to it"]'::jsonb, 'and says why');
select pg_temp.rm_assert((select not active from ingredient where id = '00000000-0000-0000-0000-000000100a02'),
  'it is kept, paused');
select pg_temp.rm_assert(exists (select 1 from match where ingredient_id = '00000000-0000-0000-0000-000000100a02'),
  'its linked notice is kept');

select pg_temp.rm_assert((:'rm_q_ing3')::jsonb ->> 'outcome' = 'paused', 'an ingredient in a product is paused');
select pg_temp.rm_assert((:'rm_q_ing3')::jsonb -> 'reasons' = '["a product: CI Prodexa"]'::jsonb, 'and names the product');
select pg_temp.rm_assert(exists (select 1 from product_ingredient where ingredient_id = '00000000-0000-0000-0000-000000100a03'),
  'the product keeps it');

select pg_temp.rm_assert((:'rm_q_ing4')::jsonb ->> 'outcome' = 'paused'
                         and (:'rm_q_ing4')::jsonb -> 'reasons' = '["been screened since 6 Nov 2026"]'::jsonb,
  'an ingredient screened since it was added is paused, even with nothing found');
select pg_temp.rm_assert(:'rm_q_direct_src' = '42501' and :'rm_q_direct_ing' = '42501',
  'an administrator cannot delete a source or an ingredient directly');
select pg_temp.rm_assert(exists (select 1 from ingredient where id = '00000000-0000-0000-0000-000000100a02'),
  'the ingredient is still there');

select pg_temp.rm_assert(:'rm_q_cat' = '22023', 'a source from the app''s own list is refused (switch it off instead)');
select pg_temp.rm_assert(exists (select 1 from source where id = 'ci-rm-catalogue'), 'the catalogue source is kept');
select pg_temp.rm_assert((:'rm_q_src3')::jsonb ->> 'outcome' = 'deleted', 'a source she added that was never read is deleted');
select pg_temp.rm_assert(not exists (select 1 from source where id = 'user-ci-rm-never'), 'it is gone');
select pg_temp.rm_assert((:'rm_q_src1')::jsonb ->> 'outcome' = 'switched_off',
  'a source read once, with nothing found, is switched off');
select pg_temp.rm_assert(exists (select 1 from source_run where source_id = 'user-ci-rm-empty'),
  'its reads stay in the screening log');
select pg_temp.rm_assert((:'rm_q_src2')::jsonb ->> 'outcome' = 'switched_off', 'a source that found something is switched off');
select pg_temp.rm_assert((select not enabled from source where id = 'user-ci-rm-found'), 'it is kept, off');
select pg_temp.rm_assert(exists (select 1 from document where source_id = 'user-ci-rm-found'), 'with what it found');

select pg_temp.rm_assert(exists (select 1 from audit_log where table_name = 'ingredient' and action = 'DELETE'
                                   and row_pk = '00000000-0000-0000-0000-000000100a01'),
  'the audit log keeps the deleted ingredient');

select pg_temp.rm_assert(
  not has_function_privilege('anon', 'public.remove_ingredient(uuid)', 'execute')
  and not has_function_privilege('anon', 'public.remove_source(text)', 'execute'),
  'signed-out visitors cannot call either');

rollback;
