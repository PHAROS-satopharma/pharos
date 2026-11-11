-- PHAROS CI — the effectiveness check day of a CAPA (0110): set by PHAROS on done (done day + 3 months), cleared
-- when it goes back to work, kept once effective; a reviewer moves it only while done, today or later, with the
-- reason; the tab reads it and ranks a done CAPA by it.
-- Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.

begin;

create function pg_temp.q_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.q_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

create function pg_temp.q_as(p uuid) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object('sub', p, 'role', 'authenticated')::text, false)
$$;

-- capa_update with the check day moved, as SQL text for q_refused.
create function pg_temp.q_move(c uuid, expected text, d date, why text) returns text language sql as $$
  select format('select capa_update(%L, %L, %L::jsonb, %L)', c, expected,
                jsonb_build_object('effectiveness_due_on', d)::text, why)
$$;

select signal_cairo_today() as today \gset

select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_open('Late case entry', 'A serious case was entered on day 16 instead of day 15.',
                      null, :'today'::date) as d1 \gset
select capa_open(:'d1', null, 'Enter the case.', 'Name a deputy.', null, 'QA (Mona)', :'today'::date + 5) as c1 \gset
select capa_open(:'d1', null, 'Train the team.', null, null, 'QA (Mona)', :'today'::date + 5) as c2 \gset
select capa_step(:'c1', 'approved', 'draft', 'Approved by QA.') as s \gset
select capa_step(:'c1', 'in_progress', 'approved') as s \gset
select pg_temp.q_refused(pg_temp.q_move(:'c1', 'in_progress', :'today'::date + 30, 'Early')) as before_done \gset
select capa_step(:'c1', 'done', 'in_progress', null, :'today'::date - 10, 'Checklist v1, DOC-PV-112.') as s \gset
select effectiveness_due_on as first_day from capa where id = :'c1' \gset
select capa_step(:'c1', 'not_effective', 'done', 'A late case again.') as s \gset
select effectiveness_due_on is null as cleared from capa where id = :'c1' \gset
select capa_step(:'c1', 'done', 'in_progress', null, null, 'Checklist v2, DOC-PV-113.') as s \gset
select effectiveness_due_on as second_day from capa where id = :'c1' \gset
select pg_temp.q_refused(pg_temp.q_move(:'c1', 'done', :'today'::date - 1, 'Sooner')) as past \gset
select pg_temp.q_refused(pg_temp.q_move(:'c1', 'done', :'today'::date + 30, null)) as no_reason \gset
select capa_update(:'c1', 'done', jsonb_build_object('effectiveness_due_on', :'today'::date + 30),
                   'The checklist is used monthly: one month is enough.') as moved \gset
reset role;

select pg_temp.q_assert(:'before_done' like '22023%once the CAPA is done%', 'the check day waits for the CAPA to be done');
select pg_temp.q_assert(:'first_day'::date = (:'today'::date - 10 + interval '3 months')::date,
  'done sets the check day three months after the day it was done');
select pg_temp.q_assert(:'cleared', 'not effective sends it back to work without a check day');
select pg_temp.q_assert(:'second_day'::date = (:'today'::date + interval '3 months')::date,
  'done again sets a new check day from the new done day');
select pg_temp.q_assert(:'past' like '22023%today or later%' and :'no_reason' like '22023%comment%',
  'a moved check day is today or later, with the reason');
select pg_temp.q_assert(
  (select effectiveness_due_on = :'today'::date + 30 from capa where id = :'c1')
  and exists (select 1 from quality_event where record_kind = 'capa' and record_id = :'c1' and step = 'updated'
                 and after ? 'effectiveness_due_on' and comment like 'The checklist%'),
  'the moved day is kept, and the history keeps the move and its reason');

-- The tab: the check day and its state; a done CAPA whose check is late comes before an open one due in 5 days.
update capa set done_on = :'today'::date - 10, effectiveness_due_on = :'today'::date - 1 where id = :'c1';
select pg_temp.q_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
create temp table q_capas as
  select c.value as c, c.ordinality as n from jsonb_array_elements(quality_state() -> 'capas') with ordinality c;
reset role;
select pg_temp.q_assert(
  (select c ->> 'effectiveness_due_on' = (:'today'::date - 1)::text and c -> 'effectiveness' ->> 'state' = 'late'
          and (c -> 'effectiveness' ->> 'days_left')::int = -1 from q_capas where c ->> 'id' = :'c1')
  and (select jsonb_typeof(c -> 'effectiveness') = 'null' from q_capas where c ->> 'id' = :'c2'),
  'the tab reads the check day of a done CAPA, and none for an open one');
select pg_temp.q_assert(
  (select n from q_capas where c ->> 'id' = :'c1') < (select n from q_capas where c ->> 'id' = :'c2'),
  'a done CAPA whose check is late is listed before an open CAPA due in 5 days');

-- Verified effective: the day is kept, and the check reads done on the day it was verified.
update capa set effectiveness_due_on = :'today'::date + 30 where id = :'c1';
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select capa_step(:'c1', 'effective', 'done', 'No late case in four weeks.') as s \gset
select c -> 'effectiveness' ->> 'state' as eff_state, c -> 'effectiveness' ->> 'done_on' as eff_done
  from jsonb_array_elements(quality_state() -> 'capas') c where c ->> 'id' = :'c1' \gset
reset role;
select pg_temp.q_assert(
  (select effectiveness_due_on = :'today'::date + 30 from capa where id = :'c1')
  and :'eff_state' = 'done' and :'eff_done' = :'today',
  'verified effective keeps the day, and the check reads done on the day it was verified');

-- A row written done (the collectors, a backfill) gets its day too; a day set later is kept.
insert into capa (year, serial, deviation_id, corrective_action, owner_other, due_on, status, evidence, done_on,
                  created_by)
values (2999, 998, :'d1', 'x', 'QA', :'today'::date, 'done', 'e', :'today'::date - 3,
        (select created_by from capa where id = :'c1')),
       (2999, 999, :'d1', 'x', 'QA', :'today'::date, 'done', 'e', :'today'::date - 3,
        (select created_by from capa where id = :'c1'));
update capa set effectiveness_due_on = :'today'::date + 7 where year = 2999 and serial = 999;
select pg_temp.q_assert(
  (select effectiveness_due_on = (:'today'::date - 3 + interval '3 months')::date from capa where year = 2999 and serial = 998)
  and (select effectiveness_due_on = :'today'::date + 7 from capa where year = 2999 and serial = 999),
  'a row written done gets its check day, and a day set later is kept');
select pg_temp.q_refused(format('update capa set effectiveness_due_on = %L where year = 2999 and serial = 998',
                                :'today'::date - 30)) as before_done_day \gset
select pg_temp.q_assert(:'before_done_day' like '23514%', 'the check day is never before the day it was done');

rollback;
