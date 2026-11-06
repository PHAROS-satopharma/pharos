-- PHAROS — the daily report (owner, 2026-11-06: "there must be also a daily report with the outcome").
--
-- The weekly report (0040) stays the report that is signed and kept for the inspection. The daily report is the
-- same report for one Cairo day, midnight to midnight, made every morning at 07:00 Cairo for the day before
-- (collectors/report.py --daily, .github/workflows/report.yml). It reads the same functions as the week
-- (ingredient_screen(), screening_log(), new_items() …: their days and instants are any range), so a day and its
-- week never disagree.
--
-- daily_report: one row per day, modelled on weekly_report. The PDF and Excel file are archived in R2 (bucket
-- lock: a day made again is stored as -r2, -r3 …) with their SHA-256, made_at, the code that made it (git_sha)
-- and the GitHub Actions run (made_by_run). Only the collector writes it; a member of the team reads it; every
-- change is in the audit log. The archive-url function serves its two files to a member of the team.

create table daily_report (
  id            uuid primary key default gen_random_uuid(),
  day           date unique not null,   -- the Cairo day it covers
  xlsx_r2_key   text not null,
  xlsx_sha256   text not null,
  pdf_r2_key    text not null,
  pdf_sha256    text not null,
  made_at       timestamptz not null default now(),
  git_sha       text,                   -- the code that made it
  made_by_run   text                    -- the GitHub Actions run that made it (its address); null when made by hand
);
comment on table daily_report is
  'One screening report per Cairo day: the archived PDF and Excel file and their SHA-256. The weekly report is the one signed.';
alter table daily_report enable row level security;
create policy daily_report_read on daily_report for select to authenticated using (my_role() is not null);
revoke all on daily_report from anon;
revoke insert, update, delete, truncate on daily_report from authenticated;
create trigger audit_daily_report after insert or update or delete on daily_report
  for each row execute function audit_row();
