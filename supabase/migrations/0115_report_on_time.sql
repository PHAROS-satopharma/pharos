-- PHAROS — the database starts the daily and weekly reports on their hour (15 Nov 2026).
--
-- report.yml was started by GitHub's own timer only, and GitHub starts a scheduled run when it can: the weekly
-- report due Sunday 15 Nov 2026 at 05:00 Cairo started at 12:17, last Sunday's at 11:40, and the daily reports
-- due at 07:00 Cairo started around 13:00–14:00. A run asked for with repository_dispatch starts within seconds
-- (0007's back-up collections, 15 Nov 2026: three seconds), so the database now asks for each report itself.
--
-- ops_report_due() lists the reports due and not yet made, in Cairo time: the weekly report of the week that
-- has just ended from Sunday 05:00 until Sunday ends, and the daily report of the day before from 07:00 until
-- the day ends. ops_kick_report() runs every hour on the hour (Cairo is a whole number of hours from UTC, so
-- 05:00 and 07:00 Cairo are always on the hour) and asks GitHub for each one (repository_dispatch "report", the
-- token of 0007). A report whose run failed is asked for again the next hour, at most four times a period, then
-- left for a person (a broken report must not run all day). GitHub's own timer stays as the back-up; every timed
-- run makes a period only when it has no report yet (report.py --if-missing), so the late one changes nothing.

create function ops_report_due(p_now timestamptz default now())
returns table (kind text, period_start date)
language sql stable
set search_path = public
as $$
  with here as (select (p_now at time zone 'Africa/Cairo') as t)
  select 'weekly', (t::date - 7)
    from here
   where extract(dow from t) = 0 and extract(hour from t) >= 5
     and not exists (select 1 from weekly_report w where w.week_start = t::date - 7)
  union all
  select 'daily', (t::date - 1)
    from here
   where extract(hour from t) >= 7
     and not exists (select 1 from daily_report d where d.day = t::date - 1)
$$;

create function ops_kick_report(p_now timestamptz default now()) returns text
language plpgsql volatile security definer
set search_path = public
as $$
declare
  v_due    record;
  v_label  text;
  v_token  text;
  v_repo   text;
  v_req    bigint;
  v_out    text[] := '{}';
begin
  for v_due in select * from ops_report_due(p_now) order by kind desc loop
    v_label := 'Start of the ' || v_due.kind || ' report of ' || to_char(v_due.period_start, 'YYYY-MM-DD');

    if (select count(*) from ops_alert_log
         where kind = 'report_kick' and message = v_label and at > p_now - interval '2 days') >= 4 then
      v_out := v_out || (v_due.kind || ': asked four times, left for a person');
      continue;
    end if;

    if v_token is null then
      begin
        execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
          into v_token using 'GITHUB_DISPATCH_TOKEN';
        execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
          into v_repo using 'GITHUB_REPO';
      exception when others then
        v_token := null;
      end;
    end if;
    if v_token is null or v_repo is null or v_repo !~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' then
      insert into ops_alert_log (kind, message, dry_run, sent, error, at)
      values ('report_kick', v_label, false, false, 'Vault secret GITHUB_DISPATCH_TOKEN or GITHUB_REPO is missing.',
              p_now);
      v_out := v_out || (v_due.kind || ': not started, Vault secrets missing');
      continue;
    end if;

    execute 'select net.http_post(url := $1, body := $2, headers := $3)'
      into v_req
      using 'https://api.github.com/repos/' || v_repo || '/dispatches',
            jsonb_build_object('event_type', 'report', 'client_payload', jsonb_build_object('kind', v_due.kind)),
            jsonb_build_object('Authorization', 'Bearer ' || v_token,
                               'Accept', 'application/vnd.github+json',
                               'X-GitHub-Api-Version', '2022-11-28',
                               'User-Agent', 'pharos-timer',
                               'Content-Type', 'application/json');
    insert into ops_alert_log (kind, message, dry_run, sent, request_id, at)
    values ('report_kick', v_label, false, true, v_req, p_now);
    v_out := v_out || (v_due.kind || ': started');
  end loop;

  return coalesce(nullif(array_to_string(v_out, '; '), ''), 'nothing due');
end $$;

revoke all on function ops_report_due(timestamptz) from public, anon, authenticated;
revoke all on function ops_kick_report(timestamptz) from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function ops_report_due(timestamptz) from service_role';
    execute 'revoke all on function ops_kick_report(timestamptz) from service_role';
  end if;
end $$;

do $do$
begin
  if not exists (select 1 from pg_extension where extname = 'pg_cron') then
    raise notice 'Not Supabase (no pg_cron): the report timer is created but not scheduled.';
    return;
  end if;
  perform cron.schedule('pharos-kick-report', '0 * * * *', $$select public.ops_kick_report()$$);
end $do$;
