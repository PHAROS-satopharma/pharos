-- PHAROS CI — an administrator who does not manage the people (0053). Runs on the database ci.yml prepared:
-- CI Admin (…a1), CI Reader (…b2), CI Reviewer (…c3) and CI Admin Two (…d4) exist. Everything happens in one
-- transaction that is rolled back at the end, so nothing is left behind.

begin;

create function pg_temp.pa_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- Row-level security refuses an insert with an error, and an update or delete by touching no rows.
create function pg_temp.pa_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return 'done';
exception when others then
  return sqlstate;
end $$;

-- CI Admin Two plays the QPPV: an administrator who does not manage the people.
update person set manages_people = false where auth_user_id = '00000000-0000-0000-0000-0000000000d4';
create temp table pa_ids as
  select (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000a1') as owner,
         (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000d4') as qppv,
         (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000b2') as reader;
grant select on pa_ids to authenticated;
select pg_temp.pa_assert((select count(*) = 0 from person where manages_people is null), 'every person has the column set');
select pg_temp.pa_assert((select manages_people from person where id = (select owner from pa_ids)),
  'an administrator manages the people by default');

-- ───────────── the QPPV: everything an administrator does, except the people ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000d4","role":"authenticated"}', false);
set role authenticated;
select my_role() = 'admin' as pa_q_admin, not i_manage_people() as pa_q_not_people \gset
select count(*) as pa_q_reads from person \gset
with u as (update person set full_name = 'Changed' where id = (select reader from pa_ids) returning 1)
select count(*) as pa_q_rename from u \gset
with u as (update person set role = 'admin' where id = (select reader from pa_ids) returning 1)
select count(*) as pa_q_promote from u \gset
with u as (update person set manages_people = true where id = (select qppv from pa_ids) returning 1)
select count(*) as pa_q_self from u \gset
with d as (delete from person where id = (select reader from pa_ids) returning 1)
select count(*) as pa_q_delete from d \gset
select pg_temp.pa_refused($q$insert into subscription (person_id, kind)
                             select reader, 'ingredient' from pa_ids$q$) as pa_q_sub_other \gset
-- Her own alerts stay hers.
select pg_temp.pa_refused($q$insert into subscription (person_id, kind)
                             select qppv, 'ingredient' from pa_ids$q$) as pa_q_sub_own \gset
-- And the rest of an administrator's work: the watchlist.
select pg_temp.pa_refused($q$insert into ingredient (inn_en) values ('ci-pa-ingredient')$q$) as pa_q_ingredient \gset
reset role;

select pg_temp.pa_assert(:'pa_q_admin', 'the QPPV is still an administrator');
select pg_temp.pa_assert(:'pa_q_not_people', 'the QPPV does not manage the people');
select pg_temp.pa_assert(:pa_q_reads >= 4, 'she still reads every person (the names on every screen)');
select pg_temp.pa_assert(:pa_q_rename = 0, 'she cannot change a person''s name');
select pg_temp.pa_assert(:pa_q_promote = 0, 'she cannot change a person''s role');
select pg_temp.pa_assert(:pa_q_self = 0, 'she cannot give herself the People screen');
select pg_temp.pa_assert(:pa_q_delete = 0, 'she cannot remove a person');
select pg_temp.pa_assert(:'pa_q_sub_other' = '42501', 'she cannot add an alert for someone else');
select pg_temp.pa_assert(:'pa_q_sub_own' = 'done', 'she still sets her own alerts');
select pg_temp.pa_assert(:'pa_q_ingredient' = 'done', 'she still adds to the watchlist, as an administrator');
select pg_temp.pa_assert((select full_name <> 'Changed' and role = 'reader' from person where id = (select reader from pa_ids)),
  'the reader is unchanged');
select pg_temp.pa_assert(not (select manages_people from person where id = (select qppv from pa_ids)),
  'she still does not manage the people');

-- ───────────── the owner still manages the people; a reader never did ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select i_manage_people() as pa_o_people \gset
with u as (update person set full_name = 'CI Reader renamed' where id = (select reader from pa_ids) returning 1)
select count(*) as pa_o_rename from u \gset
select pg_temp.pa_refused($q$insert into subscription (person_id, kind)
                             select reader, 'ingredient' from pa_ids$q$) as pa_o_sub_other \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select i_manage_people() as pa_r_people \gset
reset role;

select pg_temp.pa_assert(:'pa_o_people', 'the owner manages the people');
select pg_temp.pa_assert(:pa_o_rename = 1, 'the owner can still change a person');
select pg_temp.pa_assert(:'pa_o_sub_other' = 'done', 'the owner can still set someone else''s alerts');
select pg_temp.pa_assert(not :'pa_r_people', 'a reader does not manage the people, whatever the column says');
select pg_temp.pa_assert(
  not has_function_privilege('anon', 'public.i_manage_people()', 'execute'),
  'signed-out visitors cannot call i_manage_people');

rollback;
