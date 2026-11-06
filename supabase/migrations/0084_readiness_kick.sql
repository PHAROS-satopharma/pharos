-- PHAROS — the readiness slots are retried every hour until one of their runs starts.
--
-- The readiness work (the drug classes, the NCBI and Europe PMC look-backs and the check of the past) runs in
-- three collect.yml slots a day: daily at 02:31 UTC and literature at 10:41 and 18:41 UTC. They share GitHub's
-- "collectors" concurrency group, and GitHub keeps only ONE waiting run per group: a newer run queued behind a
-- running one cancels the run already waiting. On 6 Nov 2026 both literature slots were lost this way, and all
-- seven ingredients stayed "Still preparing" for hours. 0007's back-up timer had no literature slot, and it asks
-- once per slot, so a back-up run cancelled in its turn was not asked for again.
--
-- ops_kick_readiness() runs every hour at :29. It finds the latest readiness slot at least 40 minutes old; when
-- no daily or literature run has started since that slot (15 minutes' slack for a run started by hand just
-- before), it asks GitHub for that slot's run (repository_dispatch "collect", the same token as 0007). It asks
-- again the next hour until a run of the slot starts, and stops once the next slot is due. A run waiting in the
-- queue has not started, so it is asked for again: the new request takes the waiting one's place, with the same
-- work. It replaces 0007's once-a-day 'pharos-kick-daily', which would otherwise ask for the 02:31 slot twice.
--
-- Slot times are UTC and must match the cron lines of collect.yml (tests/test_collect_queue.py checks it).

create function ops_readiness_slot(p_now timestamptz default now())
returns table (schedule text, slot_at timestamptz)
language sql stable
set search_path = public
as $$
  select s.schedule, s.slot_at
    from (
      select x.schedule, ((d.day + x.at) at time zone 'UTC') as slot_at
        from (values ((p_now at time zone 'UTC')::date),
                     ((p_now at time zone 'UTC')::date - 1)) as d (day)
        cross join (values ('daily',      time '02:31'),
                           ('literature', time '10:41'),
                           ('literature', time '18:41')) as x (schedule, at)
    ) s
   where s.slot_at <= p_now - interval '40 minutes'
   order by s.slot_at desc
   limit 1
$$;

create function ops_kick_readiness(p_now timestamptz default now()) returns text
language plpgsql volatile security definer
set search_path = public
as $$
declare
  v_schedule text;
  v_slot     timestamptz;
  v_label    text;
  v_token    text;
  v_repo     text;
  v_req      bigint;
begin
  select r.schedule, r.slot_at into v_schedule, v_slot from ops_readiness_slot(p_now) r;
  v_label := v_schedule || ' run of ' || to_char(v_slot at time zone 'UTC', 'DD Mon HH24:MI') || ' UTC';

  if exists (select 1 from run
              where schedule in ('daily', 'literature')
                and started_at >= v_slot - interval '15 minutes') then
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
    values ('collect_kick', 'Back-up start of the ' || v_label, false, false,
            'Vault secret GITHUB_DISPATCH_TOKEN or GITHUB_REPO is missing.');
    return 'not started: Vault secrets missing';
  end if;

  execute 'select net.http_post(url := $1, body := $2, headers := $3)'
    into v_req
    using 'https://api.github.com/repos/' || v_repo || '/dispatches',
          jsonb_build_object('event_type', 'collect', 'client_payload', jsonb_build_object('schedule', v_schedule)),
          jsonb_build_object('Authorization', 'Bearer ' || v_token,
                             'Accept', 'application/vnd.github+json',
                             'X-GitHub-Api-Version', '2022-11-28',
                             'User-Agent', 'pharos-timer',
                             'Content-Type', 'application/json');
  insert into ops_alert_log (kind, message, dry_run, sent, request_id)
  values ('collect_kick', 'Back-up start of the ' || v_label
            || ' (it had not started: GitHub skipped it, or a newer run took its place in the queue)',
          false, true, v_req);
  return 'started';
end $$;

revoke all on function ops_readiness_slot(timestamptz) from public, anon, authenticated;
revoke all on function ops_kick_readiness(timestamptz) from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function ops_readiness_slot(timestamptz) from service_role';
    execute 'revoke all on function ops_kick_readiness(timestamptz) from service_role';
  end if;
end $$;

do $do$
begin
  if not exists (select 1 from pg_extension where extname = 'pg_cron') then
    raise notice 'Not Supabase (no pg_cron): the readiness timer is created but not scheduled.';
    return;
  end if;
  perform cron.unschedule(jobid) from cron.job where jobname = 'pharos-kick-daily';
  perform cron.schedule('pharos-kick-readiness', '29 * * * *', $$select public.ops_kick_readiness()$$);
end $do$;
