-- PHAROS — a fourth readiness slot: literature at 22:41 UTC (00:41 Cairo in winter).
--
-- On 6 Nov 2026 one literature run's time budget left 532 NCBI and 712 Europe PMC papers of the seven ingredients'
-- look-backs waiting, and the next readiness slot was the daily one at 02:31 UTC. collect.yml now runs literature
-- at 10:41, 18:41 and 22:41 UTC; 22:41 is clear of the 4-hour (20:17, 00:17) and 12-hour (17:47) collections.
-- ops_readiness_slot() is 0084's with that slot added, so the hourly timer (pharos-kick-readiness, :29) asks again
-- for a 22:41 run that never started, from 23:29 until the 02:31 slot is due. ops_kick_readiness() is unchanged.
--
-- Slot times are UTC and must match the cron lines of collect.yml (tests/test_collect_queue.py checks it).

create or replace function ops_readiness_slot(p_now timestamptz default now())
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
                           ('literature', time '18:41'),
                           ('literature', time '22:41')) as x (schedule, at)
    ) s
   where s.slot_at <= p_now - interval '40 minutes'
   order by s.slot_at desc
   limit 1
$$;

revoke all on function ops_readiness_slot(timestamptz) from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function ops_readiness_slot(timestamptz) from service_role';
  end if;
end $$;
