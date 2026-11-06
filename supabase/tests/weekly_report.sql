-- PHAROS CI — the weekly report (0040): the screening log for any days, the screen read by the report through a
-- direct database connection, and the weekly_report table. Runs on the database ci.yml prepared: CI Admin (…a1)
-- and CI Reader (…b2) exist. Everything happens in one transaction that is rolled back at the end.

begin;

create function pg_temp.wr_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.wr_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- ───────────── one ingredient, two authorities, three sources ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000040a001', 'CI weeklamine', 'Z98ZZ01');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-00000040c001', '00000000-0000-0000-0000-00000040a001', 'en', 'CI weeklamine');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-WR-A', 'XW', 'CI Weekland', 'CI Weekland Agency', '{en}', 'https://week.example.test/'),
  ('CI-WR-B', 'XV', 'CI Otherweek', 'CI Otherweek Agency', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-wr-a-html', 'CI-WR-A', 'safety', 'html', 'https://week.example.test/alerts', 'generic_html', '{en}',
   'https://week.example.test/alerts', true),
  ('ci-wr-a-spc', 'CI-WR-A', 'spc', 'api', 'https://week.example.test/spc.json', 'ci', '{en}', null, true),
  ('ci-wr-b-off', 'CI-WR-B', 'safety', 'html', 'https://otherweek.example.test/', 'generic_html', '{en}', null,
   false);
insert into regulator_page (regulator_id, kind, sort, label, url, read_by) values
  ('CI-WR-A', 'safety', 1, 'CI Weekland alerts', 'https://week.example.test/alerts', '{ci-wr-a-html}');

-- Reads of the week Sunday 1 Nov to Saturday 7 Nov 2026 (Cairo is UTC+2). Every run says 'backfill', as every
-- run before 6 Nov 2026 does: a read is never filtered by its run's trigger.
insert into run (id, trigger) values ('00000000-0000-0000-0000-00000040f001', 'backfill');
insert into source_run (run_id, source_id, started_at, error, items_seen, items_new, items_matched) values
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-10-31 21:00+00', null, 9, 9, 9),       -- Sat 23:00, the week before
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-10-31 22:30+00', null, 10, 2, 1),      -- Sun 00:30
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-11-03 08:00+00', 'HTTP 503 from week.example.test', 0, 0, 0),
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-11-04 08:00+00', 'HTTP 500 from week.example.test', 0, 0, 0),
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-11-05 08:00+00', 'time budget reached: CI', 12, 1, 0),
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-11-07 21:59+00', null, 11, 0, 0),      -- Sat 23:59
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-html', '2026-11-07 22:00+00', null, 5, 5, 5),       -- Sun 8 Nov 00:00
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-spc', '2026-11-02 09:00+00', 'no label read: CI', 0, 0, 0),
  ('00000000-0000-0000-0000-00000040f001', 'ci-wr-a-spc', '2026-11-20 09:00+00', null, 3, 1, 0);

-- One notice of the week naming the ingredient, filed under a notice with a decision.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at) values
  ('00000000-0000-0000-0000-00000040b001', 'ci-wr-a-html', 'w1', 'https://week.example.test/alerts/1',
   'CI weeklamine: a new warning', 'en', 'dhpc', '2026-11-03', '2026-11-03 08:00+00');
insert into match (document_id, ingredient_id, term_id, field, matched_text) values
  ('00000000-0000-0000-0000-00000040b001', '00000000-0000-0000-0000-00000040a001',
   '00000000-0000-0000-0000-00000040c001', 'title', 'CI weeklamine');
insert into issue (id, doc_type, title, anchor_document_id, first_date) values
  ('00000000-0000-0000-0000-00000040e001', 'dhpc', 'CI weeklamine: a new warning',
   '00000000-0000-0000-0000-00000040b001', '2026-11-03');
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000040e001', '00000000-0000-0000-0000-00000040b001', 'anchor', 'auto');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id)
  values ('00000000-0000-0000-0000-00000040e001', 'new', 'relevant', 'Our tablets carry it', my_person_id());
reset role;

-- ───────────── as a reader in the app ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select string_agg(source_id || ':' || runs || '/' || ok_runs || '/' || failed_runs || '/' || items_seen || '/'
                  || items_new || '/' || items_matched || '/' || coalesce(to_char(last_run at time zone 'UTC', 'MM-DD HH24:MI'), '-')
                  || '/' || coalesce(last_failure, '-') || '/' || source_kind || '/' || enabled || '/' || regulator_id
                  || '/' || country_code,
                  ' ' order by source_id) as wr_week
  from screening_log('2026-11-01', '2026-11-07') where source_id like 'ci-wr-%' \gset
select coalesce(string_agg(l.source_id, ' ' order by l.source_id), '') as wr_month_diff
  from screening_log('2026-11-01', '2026-11-30') l
  join monthly_screening_log('2026-11-01') m on m.source_id = l.source_id
 where (l.runs, l.ok_runs, l.failed_runs, l.items_seen, l.items_new, l.items_matched, l.last_run)
       is distinct from (m.runs, m.ok_runs, m.failed_runs, m.items_seen, m.items_new, m.items_matched, m.last_run) \gset
select count(*) as wr_month_rows from screening_log('2026-11-01', '2026-11-30') \gset
select count(*) as wr_monthly_rows from monthly_screening_log('2026-11-01') \gset
select ingredient_screen('00000000-0000-0000-0000-00000040a001', '2026-11-01', '2026-11-07')::text as wr_screen_app \gset
select pg_temp.wr_refused($q$select * from screening_log('2026-11-07', '2026-11-01')$q$) as wr_backwards \gset
select pg_temp.wr_refused($q$select * from screening_log('2025-11-01', '2026-11-07')$q$) as wr_too_long \gset
select pg_temp.wr_refused($q$select * from screening_log(null, '2026-11-07')$q$) as wr_no_start \gset
reset role;

select pg_temp.wr_assert(:'wr_week' =
    'ci-wr-a-html:5/3/2/33/3/1/11-07 21:59/HTTP 500 from week.example.test/safety/true/CI-WR-A/XW '
    || 'ci-wr-a-spc:1/0/1/0/0/0/11-02 09:00/no label read: CI/spc/true/CI-WR-A/XW '
    || 'ci-wr-b-off:0/0/0/0/0/0/-/-/safety/false/CI-WR-B/XV',
  'the week''s log: Sunday 00:00 to Saturday 24:00 in Cairo, every run whatever its trigger, a note is not a '
  || 'failure, the latest failure says why, and a source never read is listed with nothing');
select pg_temp.wr_assert(:'wr_month_diff' = '' and :wr_month_rows = :wr_monthly_rows,
  'over a whole month the log gives what monthly_screening_log gives, source by source');
select pg_temp.wr_assert(:'wr_backwards' like '22023%' and :'wr_too_long' like '22023%' and :'wr_no_start' like '22023%',
  'days that end before they start, more than 366 days, or no first day are refused');

-- ───────────── the report: a direct database connection, with no sign-in token ─────────────
select set_config('request.jwt.claims', '', false);
select ingredient_screen('00000000-0000-0000-0000-00000040a001', '2026-11-01', '2026-11-07')::text as wr_screen_direct \gset
select count(*) as wr_papers_direct
  from ingredient_papers('00000000-0000-0000-0000-00000040a001', '2026-11-01', '2026-11-07') \gset
select count(*) as wr_log_direct from screening_log('2026-11-01', '2026-11-07') where source_id like 'ci-wr-%' \gset
select pg_temp.wr_assert(:'wr_screen_direct' = :'wr_screen_app',
  'the report reads the Ingredients screen exactly as a member of the team sees it');
select pg_temp.wr_assert(:wr_papers_direct = 0 and :wr_log_direct = 3,
  'the report reads the papers and the screening log too');
select pg_temp.wr_assert(
  (select m -> 'decision' ->> 'to_status' = 'relevant' and m -> 'decision' ->> 'person' = 'CI Admin'
          and m -> 'decision' ->> 'comment' = 'Our tablets carry it'
     from jsonb_array_elements(:'wr_screen_direct'::jsonb -> 'regulators') r,
          jsonb_array_elements(r -> 'mentions') m
    where r ->> 'id' = 'CI-WR-A'),
  'the report sees her decision on the notice, who took it and why');

-- ───────────── who is still refused ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.wr_refused($q$select ingredient_screen('00000000-0000-0000-0000-00000040a001', '2026-11-01', '2026-11-07')$q$)
  as wr_stranger_screen \gset
select pg_temp.wr_refused($q$select * from screening_log('2026-11-01', '2026-11-07')$q$) as wr_stranger_log \gset
select pg_temp.wr_refused($q$select screen_reader()$q$) as wr_stranger_reader \gset
reset role;
select set_config('request.jwt.claims', '{"role":"service_role"}', false);
select pg_temp.wr_refused($q$select ingredient_screen('00000000-0000-0000-0000-00000040a001', '2026-11-01', '2026-11-07')$q$)
  as wr_service_screen \gset
select pg_temp.wr_refused($q$select * from screening_log('2026-11-01', '2026-11-07')$q$) as wr_service_log \gset
select set_config('request.jwt.claims', '', false);
select pg_temp.wr_assert(:'wr_stranger_screen' like '42501%' and :'wr_stranger_log' like '42501%',
  'someone signed in but not on the team is still refused the screen and the log');
select pg_temp.wr_assert(:'wr_stranger_reader' like '42501%', 'screen_reader() is not callable from the app');
select pg_temp.wr_assert(:'wr_service_screen' like '42501%' and :'wr_service_log' like '42501%',
  'a call through the API with the service key is refused: only a person on the team, or the database itself');
select pg_temp.wr_assert(
  not has_function_privilege('anon', 'public.screening_log(date, date)', 'execute')
    and has_function_privilege('authenticated', 'public.screening_log(date, date)', 'execute')
    and not has_function_privilege('anon', 'public.screen_reader()', 'execute')
    and not has_function_privilege('authenticated', 'public.ingredient_screen_check(uuid, date, date)', 'execute'),
  'signed-out visitors cannot read the log; nobody calls the checks from the app');

-- ───────────── weekly_report ─────────────
insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256, git_sha, made_by_run)
  values ('2026-11-01', '2026-11-07', 'reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01.xlsx', 'aa',
          'reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01.pdf', 'bb', 'abc123',
          'https://github.com/PHAROS-satopharma/pharos/actions/runs/1');
select pg_temp.wr_refused($q$insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2026-11-02', '2026-11-08', 'x', 'x', 'y', 'y')$q$) as wr_monday \gset
select pg_temp.wr_refused($q$insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2026-11-08', '2026-11-15', 'x', 'x', 'y', 'y')$q$) as wr_eight_days \gset
select pg_temp.wr_refused($q$insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2026-11-01', '2026-11-07', 'x', 'x', 'y', 'y')$q$) as wr_twice \gset
select pg_temp.wr_assert(:'wr_monday' like '23514%' and :'wr_eight_days' like '23514%' and :'wr_twice' like '23505%',
  'a week starts on a Sunday, ends on the Saturday after, and has one report');
select pg_temp.wr_assert(
  (select count(*) from audit_log where table_name = 'weekly_report' and action = 'INSERT'
      and new_row ->> 'week_start' = '2026-11-01') = 1,
  'the report row is in the audit log');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select count(*) as wr_reader_sees_now from weekly_report where week_start = '2026-11-01' \gset
select pg_temp.wr_refused($q$insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('2026-11-08', '2026-11-14', 'x', 'x', 'y', 'y')$q$) as wr_reader_insert \gset
select pg_temp.wr_refused($q$update weekly_report set pdf_sha256 = 'cc'$q$) as wr_reader_update \gset
select pg_temp.wr_refused($q$delete from weekly_report$q$) as wr_reader_delete \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as wr_stranger_sees from weekly_report \gset
reset role;
set role anon;
select pg_temp.wr_refused($q$select count(*) from weekly_report$q$) as wr_anon \gset
reset role;
select set_config('request.jwt.claims', '', false);
select pg_temp.wr_assert(:wr_reader_sees_now = 1 and :wr_stranger_sees = 0,
  'a member of the team reads the weekly reports; someone not on the team reads none');
select pg_temp.wr_assert(:'wr_reader_insert' like '42501%' and :'wr_reader_update' like '42501%'
    and :'wr_reader_delete' like '42501%' and :'wr_anon' like '42501%',
  'only the collector writes a weekly report; signed-out visitors read nothing');

rollback;
