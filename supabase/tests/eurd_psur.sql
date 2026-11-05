-- PHAROS CI — the EURD list and the screening summary (0028). Runs on the database ci.yml prepared: the
-- people CI Admin (…a1) and CI Reader (…b2) and the source ci-test exist.

create function pg_temp.ep_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ep_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into ingredient (id, inn_en) values ('00000000-0000-0000-0000-0000000e0a01', 'CI eurdine');
insert into eurd_entry (eurd_id, ingredient_id, substance, frequency, dlp, submission_date, generics_psur_required,
                        procedure, list_version, list_date, sha256, r2_key)
  values (9911, '00000000-0000-0000-0000-0000000e0a01', 'ci eurdine', '7 years', '2031-12-01', '2032-02-29', false,
          'PSUSA/00009911/203112', 'EMA/630645/2012 Rev.165', '2026-10-21', 'ab', 'raw/ab');

-- Two runs in June 2025 (Cairo is UTC+3): one late on the 9th in UTC, already the 10th in Cairo, which failed.
insert into run (id, trigger, started_at, finished_at, ok)
  values ('00000000-0000-0000-0000-00000000e0a1', 'cron', '2025-06-09 09:00+00', '2025-06-09 09:05+00', true);
insert into source_run (run_id, source_id, started_at, items_seen, items_matched, error) values
  ('00000000-0000-0000-0000-00000000e0a1', 'ci-test', '2025-06-09 09:00+00', 12, 2, null),
  ('00000000-0000-0000-0000-00000000e0a1', 'ci-test', '2025-06-09 21:30+00', 10, 0, 'HTTP 503');

-- A reader reads the EURD rows and the summary, and cannot change the list.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select count(*) as ep_rows from eurd_entry where eurd_id = 9911 \gset
select pg_temp.ep_refused($q$update eurd_entry set frequency = '1 year' where eurd_id = 9911$q$) as ep_upd \gset
select pg_temp.ep_refused($q$delete from eurd_entry where eurd_id = 9911$q$) as ep_del \gset
select runs as d9_runs, ok_runs as d9_ok, days_read as d9_days, items_matched as d9_matched
  from screening_summary('2025-06-09', '2025-06-09') where source_id = 'ci-test' \gset
select runs as d10_runs, failed_runs as d10_failed, days_read as d10_days
  from screening_summary('2025-06-10', '2025-06-10') where source_id = 'ci-test' \gset
select pg_temp.ep_refused($q$select * from screening_summary('2025-06-10', '2025-06-09')$q$) as ep_back \gset
reset role;

-- Nobody signed in reads nothing.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as ep_stranger from eurd_entry \gset
select pg_temp.ep_refused($q$select * from screening_summary('2025-06-01', '2025-06-30')$q$) as ep_strange \gset
reset role;

select pg_temp.ep_assert(:ep_rows = 1, 'a reader reads the EURD row of a watched ingredient');
select pg_temp.ep_assert(:'ep_upd' like '42501%' and :'ep_del' like '42501%', 'a reader cannot change the EURD list');
select pg_temp.ep_assert(:d9_runs = 1 and :d9_ok = 1 and :d9_days = 1 and :d9_matched = 2,
  'the 9th has its one morning run');
select pg_temp.ep_assert(:d10_runs = 1 and :d10_failed = 1 and :d10_days = 0,
  'a run at 21:30 UTC on the 9th counts on the 10th in Cairo, and a failed run is not a day read');
select pg_temp.ep_assert(:'ep_back' like '%end is on or after%', 'a period that ends before it starts is refused');
select pg_temp.ep_assert(:ep_stranger = 0 and :'ep_strange' like '42501%', 'someone not on the team reads nothing');

delete from run where id = '00000000-0000-0000-0000-00000000e0a1';
delete from ingredient where id = '00000000-0000-0000-0000-0000000e0a01';
