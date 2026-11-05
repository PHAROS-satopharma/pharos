-- PHAROS — a back-up timer for the scheduled collection.
--
-- GitHub's own cron is best-effort: on 4–5 Nov 2026 it started one scheduled collection in eleven hours.
-- So the database checks each slot about 50 minutes after GitHub's time, and when no run of that slot has
-- started, it asks GitHub for one (repository_dispatch "collect", the same token as the "test link" probe).
-- A slot GitHub did run is never doubled: run.schedule records which slot each run served.

alter table run add column if not exists schedule text;
create index if not exists run_schedule_started_idx on run (schedule, started_at desc);

create function ops_kick_collect(p_schedule text) returns text
language plpgsql volatile security definer
set search_path = public
as $$
declare
  v_window interval;
  v_token  text;
  v_repo   text;
  v_req    bigint;
begin
  v_window := case p_schedule
    when '4h'      then interval '3 hours'
    when '12h'     then interval '11 hours'
    when 'daily'   then interval '20 hours'
    when 'weekly'  then interval '6 days'
    when 'monthly' then interval '20 days'
  end;
  if v_window is null then
    raise exception 'unknown schedule %', p_schedule;
  end if;

  if exists (select 1 from run where schedule = p_schedule and started_at > now() - v_window) then
    return 'already ran';
  end if;

  begin
    execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
      into v_token using 'GITHUB_DISPATCH_TOKEN';
    execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
      into v_repo using 'GITHUB_REPO';
  exception when others then
    v_token := null;
  end;
  if v_token is null or v_repo is null or v_repo !~ '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' then
    insert into ops_alert_log (kind, message, dry_run, sent, error)
    values ('collect_kick', 'Back-up start of the ' || p_schedule || ' collection', false, false,
            'Vault secret GITHUB_DISPATCH_TOKEN or GITHUB_REPO is missing.');
    return 'not started: Vault secrets missing';
  end if;

  execute 'select net.http_post(url := $1, body := $2, headers := $3)'
    into v_req
    using 'https://api.github.com/repos/' || v_repo || '/dispatches',
          jsonb_build_object('event_type', 'collect', 'client_payload', jsonb_build_object('schedule', p_schedule)),
          jsonb_build_object('Authorization', 'Bearer ' || v_token,
                             'Accept', 'application/vnd.github+json',
                             'X-GitHub-Api-Version', '2022-11-28',
                             'User-Agent', 'pharos-timer',
                             'Content-Type', 'application/json');
  insert into ops_alert_log (kind, message, dry_run, sent, request_id)
  values ('collect_kick', 'Back-up start of the ' || p_schedule || ' collection (GitHub had not started it)',
          false, true, v_req);
  return 'started';
end $$;

revoke all on function ops_kick_collect(text) from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function ops_kick_collect(text) from service_role';
  end if;
end $$;

-- Times are UTC, each about 50 minutes after the matching cron in .github/workflows/collect.yml.
do $do$
begin
  if not exists (select 1 from pg_extension where extname = 'pg_cron') then
    raise notice 'Not Supabase (no pg_cron): the back-up timer is created but not scheduled.';
    return;
  end if;
  perform cron.schedule('pharos-kick-4h',      '7 1,5,9,13,17,21 * * *', $$select public.ops_kick_collect('4h')$$);
  perform cron.schedule('pharos-kick-12h',     '37 6,18 * * *',          $$select public.ops_kick_collect('12h')$$);
  perform cron.schedule('pharos-kick-daily',   '21 3 * * *',             $$select public.ops_kick_collect('daily')$$);
  perform cron.schedule('pharos-kick-weekly',  '13 4 * * 1',             $$select public.ops_kick_collect('weekly')$$);
  perform cron.schedule('pharos-kick-monthly', '31 2 1 * *',             $$select public.ops_kick_collect('monthly')$$);
end $do$;
