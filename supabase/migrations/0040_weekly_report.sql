-- PHAROS — the weekly report replaces the monthly one (2026-11-06, Dr Sama's review, point 6).
--
-- Some findings must reach the Egyptian Drug Authority within 5 days, so a monthly report comes too late. The
-- report now covers one week, Sunday to Saturday in Cairo, and is made every Sunday at 05:00 Cairo
-- (collectors/report.py, .github/workflows/report.yml). It reads the Ingredients screen through the screen's
-- own functions, so the report and the screen can never give two answers.
--
-- 1. screen_reader(): who may read the screen, the screening log and what the report is made from. A member of
--    the team signed in to the app (my_role()), or a direct database connection: the report connects as the
--    database owner through SUPABASE_DB_URL and carries no sign-in token at all. Every call through the app's
--    API carries one (request.jwt.claims, read by auth.uid()), so someone signed in but not on the team, and
--    the service key, are still refused exactly as before.
-- 2. ingredient_screen_check() (0039) asks screen_reader(): ingredient_screen() and ingredient_papers() answer
--    the report as they answer the screen. Same messages, same error codes, same grants.
-- 3. screening_log(p_from, p_to): every source and its reads in those Cairo days, both included, at most 366;
--    monthly_screening_log() (0018) for any days. A failure is what source_run_failed() says (a note is not a
--    failure), and a read is never filtered by run.trigger (every run before 6 Nov 2026 says 'backfill').
--    monthly_screening_log() stays as it is, for the monthly reports already made.
-- 4. weekly_report: one row per week, modelled on monthly_report. The PDF and Excel file are archived in R2
--    (bucket lock: never overwritten; a report made again is stored as -r2, -r3 …) with their SHA-256. made_at,
--    the code that made it (git_sha) and the GitHub Actions run that made it (made_by_run). Only the collector
--    writes it; a member of the team reads it; every change is in the audit log.

-- ───────────────────────────── who may read the screen ─────────────────────────────
create function screen_reader() returns boolean
language sql stable security definer set search_path = public as $$
  select my_role() is not null
      or (coalesce(current_setting('request.jwt.claims', true), '') = ''
          and coalesce(current_setting('request.jwt.claim.sub', true), '') = '')
$$;
revoke all on function screen_reader() from public, anon, authenticated;

-- As in 0039, asking screen_reader() instead of my_role(). create or replace keeps the owner and the revokes.
create or replace function ingredient_screen_check(p_ingredient uuid, p_from date, p_to date) returns void
language plpgsql stable security definer set search_path = public as $$
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can screen an ingredient.' using errcode = '42501';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose days whose end is on or after their start.' using errcode = '22023';
  end if;
  if p_to - p_from > 365 then
    raise exception 'Choose at most 366 days.' using errcode = '22023';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
end $$;

-- ───────────────────────────── the screening log, for any days ─────────────────────────────
create function screening_log(p_from date, p_to date)
returns table (source_id text, regulator_id text, regulator text, country text, country_code text,
               source_kind source_kind, enabled boolean, runs bigint, ok_runs bigint, failed_runs bigint,
               items_seen bigint, items_new bigint, items_matched bigint, last_run timestamptz,
               last_failure text)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
declare
  v_from timestamptz;
  v_to   timestamptz;
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can read the screening log.' using errcode = '42501';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose days whose end is on or after their start.' using errcode = '22023';
  end if;
  if p_to - p_from > 365 then
    raise exception 'Choose at most 366 days.' using errcode = '22023';
  end if;
  v_from := p_from::timestamp at time zone 'Africa/Cairo';
  v_to   := (p_to + 1)::timestamp at time zone 'Africa/Cairo';
  return query
    select s.id, r.id, r.name, r.country_name, r.country_code, s.kind, s.enabled,
           count(sr.id),
           count(sr.id) filter (where not source_run_failed(sr.error)),
           count(sr.id) filter (where source_run_failed(sr.error)),
           coalesce(sum(sr.items_seen), 0)::bigint, coalesce(sum(sr.items_new), 0)::bigint,
           coalesce(sum(sr.items_matched), 0)::bigint,
           max(sr.started_at),
           (array_agg(sr.error order by sr.started_at desc) filter (where source_run_failed(sr.error)))[1]
      from source s
      join regulator r on r.id = s.regulator_id
      left join source_run sr
        on sr.source_id = s.id
       and sr.started_at >= v_from
       and sr.started_at <  v_to
     group by s.id, r.id
     order by r.country_name, s.id;
end $$;
revoke all on function screening_log(date, date) from public, anon;
grant execute on function screening_log(date, date) to authenticated;

-- ───────────────────────────── the weekly report ─────────────────────────────
create table weekly_report (
  id            uuid primary key default gen_random_uuid(),
  week_start    date unique not null check (extract(isodow from week_start) = 7),   -- the Sunday
  week_end      date not null,                                                       -- the Saturday
  xlsx_r2_key   text not null,
  xlsx_sha256   text not null,
  pdf_r2_key    text not null,
  pdf_sha256    text not null,
  made_at       timestamptz not null default now(),
  git_sha       text,                -- the code that made it
  made_by_run   text,                -- the GitHub Actions run that made it (its address); null when made by hand
  check (week_end = week_start + 6)
);
comment on table weekly_report is
  'One screening report per Cairo week (Sunday to Saturday): the archived PDF and Excel file and their SHA-256.';
alter table weekly_report enable row level security;
create policy weekly_report_read on weekly_report for select to authenticated using (my_role() is not null);
revoke all on weekly_report from anon;
revoke insert, update, delete, truncate on weekly_report from authenticated;
create trigger audit_weekly_report after insert or update or delete on weekly_report
  for each row execute function audit_row();
