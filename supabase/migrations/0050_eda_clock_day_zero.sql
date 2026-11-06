-- PHAROS — the five-day clock, follow-up (2026-11-06): day zero is the day PHAROS first showed the notice.
--
-- A read-only review of 0041 found four things in the database; this migration fixes them.
--
-- 1. Day zero counted from the anchor document's first_seen_at. collectors/merge.py moves a notice's anchor to
--    an EMA document that arrives later, so the due day moved later unnoticed; and a notice created by a re-match
--    for an old document was late from its first moment. The owner's rule is "the day PHAROS first showed the
--    notice": the Cairo date of issue.created_at. eda_clock() counts from it when eda_day_zero is 'first_seen';
--    'decision' is unchanged. Same signature, same grants.
-- 2. A report sent to the authority is never forgotten. Concerns us, Doesn't concern us, Concerns us again used
--    to start a new clock and ask for a second report. The clock now says 'sent' when any authority_report not
--    withdrawn exists for the notice, whatever decision it was recorded under; finding_state() carries that
--    report even while the clock is off. authority_report_guard() is as it was: a new report needs Concerns us
--    as the latest decision, and is refused when that decision was reported already.
-- 3. The day a report was sent cannot be before day zero (22023), as it cannot be in the future.
-- 4. The service key (service_role, which bypasses row-level security) kept select and insert on
--    authority_report, execute on eda_clock() and latest_decision(), and select on v_eda_clock. Revoked: the
--    collectors read the clock on their direct connection (the owner), the app through finding_state().

-- ───────────────────────────── the clock ─────────────────────────────
create or replace function eda_clock(p_issues uuid[])
returns table (
  issue_id       uuid,
  ingredient_id  uuid,
  ingredient     text,
  title          text,
  country        text,
  regulator      text,
  day_zero       date,
  due            date,
  days_left      int,
  clock          text,
  decided_at     timestamptz,
  decided_by     text,
  sent_id        uuid,
  sent_on        date,
  sent_reference text,
  sent_note      text,
  sent_by        text
)
language sql stable security definer set search_path = public as $$
  with settings as (
    select coalesce((select nullif(value #>> '{}', '')::int from app_setting where key = 'eda_days'), 5) as days,
           coalesce((select value #>> '{}' from app_setting where key = 'eda_day_zero'), 'first_seen') as zero,
           signal_cairo_today() as today
  ),
  base as (
    select i.id, i.title, i.created_at as issue_created_at, s.regulator_id,
           dec.id as decision_id, dec.to_status, dec.created_at as decided_at, dec.person_id as decided_by_id
      from issue i
      left join document ad on ad.id = i.anchor_document_id
      left join source s on s.id = ad.source_id
      left join lateral (select * from latest_decision(i.id)) dec on true
     where (p_issues is null and i.status = 'relevant' and dec.to_status = 'relevant')
        or (p_issues is not null and i.id = any (p_issues))
  ),
  clocked as (
    -- Day zero: the Cairo day PHAROS first showed the notice, which is the day its row was created (0050); or
    -- the day of the decision when the setting says so.
    select b.*, st.today, st.days,
           case when st.zero = 'decision' and b.decided_at is not null
                then (b.decided_at at time zone 'Africa/Cairo')::date
                else (b.issue_created_at at time zone 'Africa/Cairo')::date
           end as day_zero,
           ar.id as sent_id, ar.sent_on, ar.reference, ar.note, ar.person_id as sent_by_id
      from base b
     cross join settings st
      -- The latest report to the authority not withdrawn, under whatever decision it was recorded: a report
      -- sent is never forgotten (0050).
      left join lateral (
        select * from authority_report ar
         where ar.issue_id = b.id and ar.withdrawn_at is null
         order by ar.created_at desc limit 1
      ) ar on true
  )
  select c.id,
         ing.id,
         ing.inn_en,
         c.title,
         r.country_name,
         r.name,
         c.day_zero,
         c.day_zero + c.days,
         (c.day_zero + c.days) - c.today,
         case when c.to_status is distinct from 'relevant' then 'off'
              when c.sent_on is not null then 'sent'
              when c.today > c.day_zero + c.days then 'late'
              else 'running' end,
         c.decided_at,
         pd.full_name,
         c.sent_id,
         c.sent_on,
         c.reference,
         c.note,
         ps.full_name
    from clocked c
    left join regulator r on r.id = c.regulator_id
    left join person pd on pd.id = c.decided_by_id
    left join person ps on ps.id = c.sent_by_id
    left join lateral (
      select g.id, g.inn_en from issue_ingredient ii join ingredient g on g.id = ii.ingredient_id
       where ii.issue_id = c.id order by lower(g.inn_en), g.id limit 1
    ) ing on true
$$;
revoke all on function eda_clock(uuid[]) from public, anon, authenticated;

-- ───────────────────────────── the day sent is never before day zero ─────────────────────────────
create or replace function authority_report_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_dec      review_event;
  v_day_zero date;
begin
  new.created_at := clock_timestamp();
  if new.withdrawn_at is not null or new.withdrawn_by is not null or new.withdraw_reason is not null then
    raise exception 'A report is withdrawn after it is recorded, not as it is recorded.' using errcode = '22023';
  end if;
  if new.sent_on > signal_cairo_today() then
    raise exception 'The day it was sent cannot be in the future.' using errcode = '22023';
  end if;
  -- The same lock the decisions take, so a decision and a report on one notice are ordered.
  perform 1 from issue where id = new.issue_id for update;
  if not found then
    raise exception 'That notice no longer exists.' using errcode = '23503';
  end if;
  v_dec := latest_decision(new.issue_id);
  if v_dec.id is null or v_dec.to_status <> 'relevant' then
    raise exception 'NO_CONCERN: only a notice whose latest decision is Concerns us can be reported to the authority.'
      using errcode = 'PH409', hint = 'Record Concerns us first, or reload the notice.';
  end if;
  if exists (select 1 from authority_report ar where ar.decision_id = v_dec.id and ar.withdrawn_at is null) then
    raise exception 'ALREADY_SENT: this decision was already reported to the authority.'
      using errcode = 'PH409', hint = 'Withdraw the earlier report first if it was wrong.';
  end if;
  -- The day it was sent cannot be before the day PHAROS first showed the notice (0050): earlier is a typo.
  select c.day_zero into v_day_zero from eda_clock(array[new.issue_id]) c;
  if v_day_zero is not null and new.sent_on < v_day_zero then
    raise exception 'The day it was sent cannot be before %, the day PHAROS first showed this notice.',
      to_char(v_day_zero, 'FMDD Mon YYYY')
      using errcode = '22023';
  end if;
  new.decision_id := v_dec.id;
  return new;
end $$;

-- ───────────────────────────── the service key reads none of it ─────────────────────────────
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on authority_report from service_role';
    execute 'revoke all on function eda_clock(uuid[]) from service_role';
    execute 'revoke all on function latest_decision(uuid) from service_role';
    execute 'revoke all on v_eda_clock from service_role';
  end if;
end $$;
