-- PHAROS CI — the database starts the daily and weekly reports on their hour (0115): ops_report_due() and
-- ops_kick_report(). The times are in 2031, after every report ci.yml recorded. Everything happens in one
-- transaction that is rolled back at the end.

begin;

create function pg_temp.rp_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.rp_due(p_now timestamptz) returns text language sql as $$
  select coalesce(string_agg(kind || ' ' || period_start, ', ' order by kind desc), 'none') from ops_report_due(p_now)
$$;

-- ───────────── which report is due, in Cairo time ─────────────
-- Sunday 9 Mar 2031; Cairo is UTC+2 in March.
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-09 02:59+00') = 'none',
  'at 04:59 Cairo on Sunday nothing is due: the week has its report from 05:00');
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-09 03:00+00') = 'weekly 2031-03-02',
  'at 05:00 Cairo on Sunday the week that has just ended (Sunday 2 to Saturday 8 March) is due');
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-09 05:00+00') = 'weekly 2031-03-02, daily 2031-03-08',
  'at 07:00 Cairo the daily report of Saturday is due too');
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-10 04:59+00') = 'none'
                     and pg_temp.rp_due('2031-03-10 05:00+00') = 'daily 2031-03-09',
  'on Monday only the daily report, from 07:00 Cairo: a week is asked for on its Sunday only');
-- Sunday 6 July 2031; Cairo is UTC+3 in summer, so 05:00 Cairo is 02:00 UTC.
select pg_temp.rp_assert(pg_temp.rp_due('2031-07-06 01:59+00') = 'none'
                     and pg_temp.rp_due('2031-07-06 02:00+00') = 'weekly 2031-06-29',
  'in summer the week is due at 05:00 Cairo all the same (02:00 UTC)');
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-08 23:30+00') = 'none',
  'at 01:30 Cairo on Sunday (still Saturday in UTC) nothing is due yet');

-- ───────────── a report that is made is never asked for again ─────────────
insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2031-03-02', '2031-03-08', 'x', 'x', 'y', 'y');
insert into daily_report (day, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2031-03-08', 'x', 'x', 'y', 'y');
select pg_temp.rp_assert(pg_temp.rp_due('2031-03-09 05:00+00') = 'none'
                     and ops_kick_report('2031-03-09 05:00+00') = 'nothing due',
  'once the week and the day have their reports, nothing is asked for');
rollback;
begin;

create function pg_temp.rp_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- ───────────── asking GitHub: logged, and at most four times a period ─────────────
-- No Vault secret in CI: the request is not sent, and the log says which report and why.
select ops_kick_report('2031-03-09 03:00+00') as k1 \gset
select pg_temp.rp_assert(:'k1' = 'weekly: not started, Vault secrets missing'
    and exists (select 1 from ops_alert_log where kind = 'report_kick' and not sent
                 and message = 'Start of the weekly report of 2031-03-02'),
  'a week with no report is asked for, with the week in the log');

select ops_kick_report('2031-03-09 04:00+00') as k2 \gset
select ops_kick_report('2031-03-09 05:00+00') as k3 \gset
select pg_temp.rp_assert(:'k3' = 'weekly: not started, Vault secrets missing; daily: not started, Vault secrets missing',
  'at 07:00 Cairo the week and the day are both asked for');
select ops_kick_report('2031-03-09 06:00+00') as k4 \gset
select ops_kick_report('2031-03-09 07:00+00') as k5 \gset
select pg_temp.rp_assert(:'k5' = 'weekly: asked four times, left for a person; daily: not started, Vault secrets missing'
    and (select count(*) from ops_alert_log where kind = 'report_kick'
           and message = 'Start of the weekly report of 2031-03-02') = 4,
  'a report whose runs keep failing is asked for four times, then left for a person');

select pg_temp.rp_assert(not has_function_privilege('anon', 'ops_kick_report(timestamptz)', 'execute')
                     and not has_function_privilege('authenticated', 'ops_kick_report(timestamptz)', 'execute'),
  'no signed-in or anonymous caller can start a report');

rollback;
