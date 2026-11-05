-- PHAROS — the inspection pack (2026-11-05).
--
-- The Reports screen builds one workbook an inspector can read without the app: what PHAROS is, which
-- source was read on which Cairo day, every notice and every decision on it, the signals, the alerts, the
-- audit trail and the archive checks. This function gives the coverage calendar: one row per source and
-- Cairo day on which it ran, counted the same way as the screening log (source_run_failed, 0018).
--
-- Administrators only: the pack carries the audit trail and every alert, which only they may read. A period
-- is at most 366 days, so the calendar stays one sheet.

create function inspection_coverage(p_from date, p_to date)
returns table (source_id text, day date, runs bigint, ok_runs bigint, failed_runs bigint,
               items_seen bigint, items_matched bigint)
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can build the inspection pack.' using errcode = '42501';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose a period whose end is on or after its start.' using errcode = '22023';
  end if;
  if p_to - p_from > 365 then
    raise exception 'The inspection pack covers at most 366 days.' using errcode = '22023';
  end if;
  return query
    select sr.source_id,
           (sr.started_at at time zone 'Africa/Cairo')::date as day,
           count(*),
           count(*) filter (where not source_run_failed(sr.error)),
           count(*) filter (where source_run_failed(sr.error)),
           coalesce(sum(sr.items_seen), 0)::bigint,
           coalesce(sum(sr.items_matched), 0)::bigint
      from source_run sr
     where sr.started_at >= (p_from::timestamp at time zone 'Africa/Cairo')
       and sr.started_at <  ((p_to + 1)::timestamp at time zone 'Africa/Cairo')
     group by sr.source_id, 2
     order by sr.source_id, 2;
end $$;

revoke all on function inspection_coverage(date, date) from public, anon;
grant execute on function inspection_coverage(date, date) to authenticated;
