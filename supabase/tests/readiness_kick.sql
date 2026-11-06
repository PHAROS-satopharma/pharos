-- PHAROS CI — the readiness slots' hourly back-up timer (0084): ops_readiness_slot() and ops_kick_readiness().
-- The times are in 2031, after every run ci.yml recorded, so only the runs inserted here count. Everything
-- happens in one transaction that is rolled back at the end.

begin;

create function pg_temp.rk_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.rk_slot(p_now timestamptz) returns text language sql as $$
  select schedule || ' ' || to_char(slot_at at time zone 'UTC', 'YYYY-MM-DD HH24:MI') from ops_readiness_slot(p_now)
$$;

-- ───────────── which slot is due ─────────────
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 11:29+00') = 'literature 2031-03-04 10:41',
  'at 11:29 UTC the 10:41 literature slot is due');
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 11:20+00') = 'literature 2031-03-04 10:41'
                     and pg_temp.rk_slot('2031-03-04 11:19+00') = 'daily 2031-03-04 02:31',
  'a slot is due 40 minutes after its time, not before: GitHub''s own cron goes first');
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 19:29+00') = 'literature 2031-03-04 18:41',
  'at 19:29 UTC the 18:41 literature slot is due');
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 03:29+00') = 'daily 2031-03-04 02:31',
  'at 03:29 UTC the 02:31 daily slot is due');
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 00:29+00') = 'literature 2031-03-03 18:41',
  'after midnight the evening literature slot of the day before is still the one retried');
select pg_temp.rk_assert(pg_temp.rk_slot('2031-03-04 02:29+02') = 'literature 2031-03-03 18:41',
  'the slots are UTC whatever the time zone the time is given in');

-- ───────────── a lost literature run is asked for again, every hour, until one starts ─────────────
-- No Vault secret in CI: the request is not sent, and the log says which slot and why.
select ops_kick_readiness('2031-03-04 11:29+00') as k1 \gset
select pg_temp.rk_assert(:'k1' = 'not started: Vault secrets missing'
    and exists (select 1 from ops_alert_log where kind = 'collect_kick' and not sent
                 and message = 'Back-up start of the literature run of 04 Mar 10:41 UTC'),
  'a literature slot no run started is asked for, with its slot in the log');

-- The daily run of the same morning does not count for the 10:41 slot: the look-backs it did are hours old.
insert into run (trigger, schedule, started_at) values ('cron', 'daily', '2031-03-04 02:35+00');
select ops_kick_readiness('2031-03-04 12:29+00') as k2 \gset
select pg_temp.rk_assert(:'k2' <> 'already ran', 'the morning''s daily run does not stand for the 10:41 literature slot');

-- Neither do the runs of other schedules, nor a one-source or one-ingredient run (they record no schedule).
insert into run (trigger, schedule, started_at) values
  ('cron', '4h', '2031-03-04 13:17+00'), ('manual', null, '2031-03-04 13:20+00'), ('backfill', null, '2031-03-04 13:00+00');
select ops_kick_readiness('2031-03-04 13:29+00') as k3 \gset
select pg_temp.rk_assert(:'k3' <> 'already ran',
  'a 4-hour, one-source or backfill run does not stand for the literature slot: it is asked for again');

-- Once a literature run of the slot has started, nothing more is asked for.
insert into run (trigger, schedule, started_at) values ('cron', 'literature', '2031-03-04 14:02+00');
select ops_kick_readiness('2031-03-04 14:29+00') as k4 \gset
select pg_temp.rk_assert(:'k4' = 'already ran', 'a slot whose run started is not asked for twice');

-- A literature run started by hand just before the slot counts for it (15 minutes' slack); one long before does not.
insert into run (trigger, schedule, started_at) values ('manual', 'literature', '2031-03-05 18:30+00');
select ops_kick_readiness('2031-03-05 19:29+00') as k5 \gset
insert into run (trigger, schedule, started_at) values ('manual', 'literature', '2031-03-06 18:00+00');
select ops_kick_readiness('2031-03-06 19:29+00') as k6 \gset
select pg_temp.rk_assert(:'k5' = 'already ran' and :'k6' <> 'already ran',
  'a run started up to 15 minutes before the slot stands for it, one 41 minutes before does not');

-- The daily slot: retried the same way.
select ops_kick_readiness('2031-03-07 04:29+00') as k7 \gset
insert into run (trigger, schedule, started_at) values ('cron', 'daily', '2031-03-07 04:31+00');
select ops_kick_readiness('2031-03-07 05:29+00') as k8 \gset
select pg_temp.rk_assert(:'k7' <> 'already ran' and :'k8' = 'already ran'
    and exists (select 1 from ops_alert_log where kind = 'collect_kick' and message like '%daily run of 07 Mar 02:31 UTC%'),
  'a daily slot no run started is asked for until one starts');

-- ───────────── who may call it ─────────────
select pg_temp.rk_assert(not has_function_privilege('authenticated', 'public.ops_kick_readiness(timestamptz)', 'execute')
    and not has_function_privilege('anon', 'public.ops_kick_readiness(timestamptz)', 'execute')
    and not has_function_privilege('service_role', 'public.ops_kick_readiness(timestamptz)', 'execute'),
  'nobody but the database''s own timer can start collections through it');

rollback;
