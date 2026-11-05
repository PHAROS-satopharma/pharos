-- PHAROS CI — the inspection pack's coverage calendar (0026). Runs on the database ci.yml prepared: the
-- people CI Admin (…a1) and CI Reader (…b2) and the source ci-test exist.

create function pg_temp.ip_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ip_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- Three runs in March 2025 (Cairo is UTC+2): one late on the 3rd in UTC, which is already the 4th in Cairo,
-- one failed and one with a note that is not a failure.
insert into run (id, trigger, started_at, finished_at, ok)
  values ('00000000-0000-0000-0000-00000000c0a1', 'cron', '2025-03-03 09:00+00', '2025-03-03 09:05+00', true);
insert into source_run (run_id, source_id, started_at, items_seen, items_matched, error) values
  ('00000000-0000-0000-0000-00000000c0a1', 'ci-test', '2025-03-03 09:00+00', 12, 1, null),
  ('00000000-0000-0000-0000-00000000c0a1', 'ci-test', '2025-03-03 22:30+00', 10, 0, 'HTTP 503'),
  ('00000000-0000-0000-0000-00000000c0a1', 'ci-test', '2025-03-04 08:00+00', 9, 0, 'time budget reached: stopped early');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ip_refused($q$select * from inspection_coverage('2025-03-01', '2025-03-31')$q$) as ip_reader \gset
reset role;
select pg_temp.ip_assert(:'ip_reader' like '42501%', 'a reader cannot build the inspection pack');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ip_refused($q$select * from inspection_coverage('2025-01-01', '2026-01-02')$q$) as ip_long \gset
select runs as d3_runs, ok_runs as d3_ok from inspection_coverage('2025-03-01', '2025-03-31') where day = '2025-03-03' \gset
select runs as d4_runs, ok_runs as d4_ok, failed_runs as d4_failed, items_seen as d4_seen
  from inspection_coverage('2025-03-01', '2025-03-31') where day = '2025-03-04' \gset
select count(*) as ip_edge from inspection_coverage('2025-03-04', '2025-03-04') \gset
reset role;
select pg_temp.ip_assert(:'ip_long' like '%at most 366 days%', 'a period longer than 366 days is refused');
select pg_temp.ip_assert(:d3_runs = 1 and :d3_ok = 1, 'the 3rd has its one morning run');
select pg_temp.ip_assert(:d4_runs = 2 and :d4_ok = 1 and :d4_failed = 1 and :d4_seen = 19,
  'a run at 22:30 UTC on the 3rd counts on the 4th in Cairo, and a note is not a failure');
select pg_temp.ip_assert(:ip_edge = 1, 'a one-day period reads that Cairo day only');

delete from run where id = '00000000-0000-0000-0000-00000000c0a1';
