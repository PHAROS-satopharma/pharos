-- PHAROS — the weekly label watch has its own workflow (13 Nov 2026).
--
-- The label (SPC) watch used to be collect.yml's weekly run: seventeen sources sharing 78 minutes, about 4.6 each,
-- so on 9 Nov DailyMed, CIMA and the MHRA read no label. It is now label-watch.yml, one job per source, each with
-- 330 minutes. 0007's back-up timer (pharos-kick-weekly, Monday 04:13 UTC) asks GitHub for the weekly slot when no
-- run of it started; it now sends the event "label-watch" for that slot, and "collect" for every other one, as
-- before. Each label-watch job records run.schedule = 'weekly', so a week GitHub did start is never doubled.
-- The function is 0007's with only the event name changed; its grants are unchanged.

create or replace function ops_kick_collect(p_schedule text) returns text
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
          jsonb_build_object('event_type', case when p_schedule = 'weekly' then 'label-watch' else 'collect' end,
                             'client_payload', jsonb_build_object('schedule', p_schedule)),
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
