-- PHAROS — the five-day clock to the Egyptian Drug Authority (2026-11-06, the QPPV's first need after her review).
--
-- A finding that concerns us must reach the Egyptian Drug Authority within five days. The owner decided
-- (6 Nov 2026) that the days count from the day PHAROS first showed the notice. This migration gives every
-- notice a clock the screen, the weekly report and the morning reminder all read from one function.
--
-- 1. app_setting: eda_days (5) and eda_day_zero ('first_seen'; 'decision' counts from the day of the decision).
-- 2. authority_report: one row each time a finding is reported to the authority (date sent, reference, note,
--    who recorded it, which decision it answers). Append-only and audited; the team reads it; a reviewer or
--    administrator records her own row, and only while the notice's latest decision is Concerns us
--    (PH409 NO_CONCERN otherwise; PH409 ALREADY_SENT when that decision was reported already; 22023 for a date
--    in the future). A wrong row is withdrawn with withdraw_authority_report(id, reason), never deleted.
-- 3. eda_clock(p_issues) is the one computation: per notice its day zero (Cairo date of the anchor document's
--    first_seen_at), the due day, the days left, and the clock: 'off' while the latest decision is not Concerns
--    us (or there is none), 'sent' when an authority_report not withdrawn answers that decision, 'late' when
--    today in Cairo is past the due day, else 'running'. finding_state(p_issues) returns it as jsonb for the
--    screen (a member of the team) and the weekly report (direct connection, screen_reader() as 0040);
--    v_eda_clock lists the running and late clocks for the collectors' morning reminder.
-- 4. review_event_guard() stamps decisions with clock_timestamp() instead of now(): still the database's
--    clock, never the browser's, but two decisions in one transaction keep their order (the CI tests take
--    every step in one transaction, and the latest decision must be the latest).

-- ───────────────────────────── settings ─────────────────────────────
insert into app_setting (key, value) values ('eda_days', '5'), ('eda_day_zero', '"first_seen"')
  on conflict (key) do nothing;

-- ───────────────────────────── decisions keep their order ─────────────────────────────
create or replace function review_event_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_current issue_status;
begin
  -- The database's clock, never the browser's; clock_timestamp() so that two decisions in one transaction
  -- are still one after the other.
  new.created_at := clock_timestamp();

  -- Lock the notice so two decisions on it are taken one after the other, each against the true status.
  select status into v_current from issue where id = new.issue_id for update;
  if not found then
    raise exception 'That notice no longer exists.' using errcode = '23503';
  end if;

  if new.to_status = 'new' then
    raise exception 'A decision cannot move a notice back to New.' using errcode = '22023';
  end if;
  if new.from_status is distinct from v_current then
    raise exception 'STALE_DECISION: someone else recorded a decision on this notice a moment ago; it is now %.',
      v_current
      using errcode = 'PH409',
            hint = 'Reload the notice and decide again.';
  end if;
  if new.to_status = new.from_status then
    raise exception 'The notice already has that status.' using errcode = '22023';
  end if;
  return new;
end $$;

-- ───────────────────────────── reported to the authority ─────────────────────────────
create table authority_report (
  id              uuid primary key default gen_random_uuid(),
  issue_id        uuid not null references issue(id) on delete cascade,
  authority       text not null default 'EDA',
  sent_on         date not null,
  reference       text,
  note            text,
  person_id       uuid not null references person(id),
  decision_id     uuid not null references review_event(id),   -- the Concerns us it answers (set by the guard)
  created_at      timestamptz not null default now(),
  withdrawn_at    timestamptz,
  withdrawn_by    uuid references person(id),
  withdraw_reason text,
  check (withdrawn_at is null or length(coalesce(trim(withdraw_reason), '')) > 0)
);
comment on table authority_report is
  'Each time a finding was reported to the Egyptian Drug Authority: when, under which reference, by whom, and '
  'which decision it answers. Append-only; a wrong row is withdrawn, never deleted.';
create index authority_report_issue_idx on authority_report (issue_id, created_at desc);
create index authority_report_decision_idx on authority_report (decision_id) where withdrawn_at is null;

alter table authority_report enable row level security;
create policy authority_report_read on authority_report for select to authenticated using (my_role() is not null);
create policy authority_report_write on authority_report for insert to authenticated
  with check (my_role() in ('admin', 'reviewer') and person_id = my_person_id());
revoke all on authority_report from anon;
revoke update, delete, truncate on authority_report from authenticated;
create trigger audit_authority_report after insert or update or delete on authority_report
  for each row execute function audit_row();

-- Append-only: the only change ever allowed is one withdrawal, made through withdraw_authority_report().
create function authority_report_immutable() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE'
     and old.withdrawn_at is null and new.withdrawn_at is not null
     and coalesce(current_setting('pharos.withdrawing', true), '') = new.id::text
     and (new.id, new.issue_id, new.authority, new.sent_on, new.reference, new.note, new.person_id,
          new.decision_id, new.created_at)
         = (old.id, old.issue_id, old.authority, old.sent_on, old.reference, old.note, old.person_id,
            old.decision_id, old.created_at) then
    return new;
  end if;
  raise exception 'authority_report is append-only';
end $$;
create trigger authority_report_no_update before update or delete on authority_report
  for each row execute function authority_report_immutable();

-- The latest decision on a notice: the Concerns us the report answers, or nothing.
create function latest_decision(p_issue uuid) returns review_event
language sql stable security definer set search_path = public as $$
  select re.* from review_event re where re.issue_id = p_issue order by re.created_at desc, re.id desc limit 1
$$;
revoke all on function latest_decision(uuid) from public, anon, authenticated;

create function authority_report_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_dec review_event;
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
  new.decision_id := v_dec.id;
  return new;
end $$;
create trigger authority_report_guard before insert on authority_report
  for each row execute function authority_report_guard();

-- A wrong "sent" is withdrawn by a reviewer or administrator, with a reason; the row stays as evidence.
create function withdraw_authority_report(p_id uuid, p_reason text) returns void
language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := my_person_id();
begin
  if my_role() not in ('admin', 'reviewer') or v_person is null then
    raise exception 'Only a reviewer or an administrator can withdraw a report to the authority.'
      using errcode = '42501';
  end if;
  if length(coalesce(trim(p_reason), '')) = 0 then
    raise exception 'Say why the report is withdrawn.' using errcode = '22023';
  end if;
  if not exists (select 1 from authority_report where id = p_id and withdrawn_at is null) then
    raise exception 'That report does not exist or was withdrawn already.' using errcode = 'P0002';
  end if;
  perform set_config('pharos.withdrawing', p_id::text, true);
  update authority_report
     set withdrawn_at = clock_timestamp(), withdrawn_by = v_person, withdraw_reason = trim(p_reason)
   where id = p_id;
  perform set_config('pharos.withdrawing', '', true);
end $$;
revoke all on function withdraw_authority_report(uuid, text) from public, anon;
grant execute on function withdraw_authority_report(uuid, text) to authenticated;

-- ───────────────────────────── the clock ─────────────────────────────
-- One computation for the screen, the report and the reminder. p_issues null: every notice whose latest
-- decision is Concerns us (what the collectors need).
create function eda_clock(p_issues uuid[])
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
    select i.id, i.title, i.created_at as issue_created_at, ad.first_seen_at, s.regulator_id,
           dec.id as decision_id, dec.to_status, dec.created_at as decided_at, dec.person_id as decided_by_id
      from issue i
      left join document ad on ad.id = i.anchor_document_id
      left join source s on s.id = ad.source_id
      left join lateral (select * from latest_decision(i.id)) dec on true
     where (p_issues is null and i.status = 'relevant' and dec.to_status = 'relevant')
        or (p_issues is not null and i.id = any (p_issues))
  ),
  clocked as (
    select b.*, st.today, st.days,
           case when st.zero = 'decision' and b.decided_at is not null
                then (b.decided_at at time zone 'Africa/Cairo')::date
                else (coalesce(b.first_seen_at, b.issue_created_at) at time zone 'Africa/Cairo')::date
           end as day_zero,
           ar.sent_on, ar.reference, ar.note, ar.person_id as sent_by_id
      from base b
     cross join settings st
      left join lateral (
        select * from authority_report ar
         where ar.decision_id = b.decision_id and ar.withdrawn_at is null
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

create function finding_state(p_issues uuid[]) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can read the clock.' using errcode = '42501';
  end if;
  if p_issues is null or cardinality(p_issues) = 0 then
    return '{}'::jsonb;
  end if;
  return coalesce((
    select jsonb_object_agg(c.issue_id::text, jsonb_build_object(
             'day_zero', c.day_zero,
             'due', c.due,
             'days_left', c.days_left,
             'clock', c.clock,
             'sent', case when c.sent_on is null then null
                          else jsonb_build_object('on', c.sent_on, 'reference', c.sent_reference,
                                                  'person', c.sent_by, 'note', c.sent_note) end))
      from eda_clock(p_issues) c), '{}'::jsonb);
end $$;
revoke all on function finding_state(uuid[]) from public, anon;
grant execute on function finding_state(uuid[]) to authenticated;

-- The running and late clocks, for the collectors' morning reminder (owner connection only).
create view v_eda_clock as
  select issue_id, ingredient_id, ingredient, title, country, regulator, day_zero, due, days_left, clock,
         decided_at, decided_by
    from eda_clock(null)
   where clock in ('running', 'late');
revoke all on v_eda_clock from public, anon, authenticated;
