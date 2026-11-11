-- PHAROS — proposed deviations (2026-11-11). PHAROS already knows every deadline it keeps: the five-day clock to
-- the Egyptian Drug Authority (0041/0050), the steps of a signal (0042), the due day of a CAPA and the
-- deadlines of an audit (0107). A deadline that passes without being met is a deviation under PV-SOP-021 — so
-- once a Cairo day PHAROS writes it down as a PROPOSED deviation, and a reviewer or an administrator decides:
-- record it as a deviation (it then gets its D-number through the one code path, deviation_open_as(), and its
-- history) or dismiss it with the reason. Nothing is recorded, approved or closed by PHAROS itself.
--
-- 1. deviation_proposal: one row per missed deadline, never twice: unique (source_kind, source_id, source_step).
--    source_step tells two misses of one record apart (the stage of a signal, the day zero of a clock, the due
--    day of a CAPA, the deadline key of an audit). A dismissed proposal is kept, with its reason, and the same
--    missed deadline is never proposed again.
-- 2. app_setting 'deviation_proposals_since': the Cairo day this migration ran. Only a deadline due on or after
--    it is proposed — PHAROS never fills the list with deadlines missed before it began to look.
-- 3. deviation_proposals_find(day): the collectors' daily run (collectors/quality.py, on the morning reminder's
--    schedule). Granted to nobody: the collectors call it on their direct connection (the owner).
-- 4. deviation_proposals(): what the Quality tab reads (everyone signed in). deviation_proposal_confirm() and
--    deviation_proposal_dismiss(): a reviewer or an administrator.

-- ───────────────────────────── 1. the table ─────────────────────────────
create table deviation_proposal (
  id                     uuid primary key default gen_random_uuid(),
  source_kind            text not null check (source_kind in ('eda_clock', 'signal_step', 'capa', 'audit_deadline')),
  source_id              uuid not null,
  source_step            text not null default '',
  source_ref             text,             -- what she knows it by: the signal ref, the CAPA ref, the audit title
  ingredient_id          uuid references ingredient(id) on delete set null,
  title                  text not null check (length(trim(title)) > 0),
  description            text not null check (length(trim(description)) > 0),
  occurred_on            date not null,    -- the day the deadline fell due
  detected_on            date not null,    -- the Cairo day PHAROS found it missed
  patient_safety         boolean not null default false,
  regulatory_compliance  boolean not null default false,
  document_quality       boolean not null default false,
  status                 text not null default 'proposed' check (status in ('proposed', 'confirmed', 'dismissed')),
  dismissed_reason       text,
  deviation_id           uuid references deviation(id),
  decided_by             uuid references person(id),
  decided_at             timestamptz,
  created_at             timestamptz not null default now(),
  unique (source_kind, source_id, source_step),
  check (occurred_on < detected_on),
  check (status <> 'confirmed' or (deviation_id is not null and decided_by is not null and decided_at is not null)),
  check (status <> 'dismissed' or (length(trim(coalesce(dismissed_reason, ''))) > 0
                                   and decided_by is not null and decided_at is not null)),
  check (status <> 'proposed' or (deviation_id is null and decided_by is null and dismissed_reason is null))
);
comment on table deviation_proposal is
  'A deadline PHAROS kept that passed unmet, proposed as a deviation (PV-SOP-021) for a person to record or dismiss (0108).';
create index on deviation_proposal (status, occurred_on);

create trigger audit_deviation_proposal after insert or update or delete on deviation_proposal
  for each row execute function audit_row();
alter table deviation_proposal enable row level security;
create policy deviation_proposal_read on deviation_proposal for select to authenticated using (my_role() is not null);
revoke all on deviation_proposal from public, anon;
revoke insert, update, delete, truncate on deviation_proposal from authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on deviation_proposal from service_role';
  end if;
end $$;

-- ───────────────────────────── 2. from when ─────────────────────────────
insert into app_setting (key, value)
values ('deviation_proposals_since', to_jsonb(signal_cairo_today()::text))
on conflict (key) do nothing;

-- ───────────────────────────── 3. the daily run ─────────────────────────────
-- A day in her words: "Tue 3 Nov 2026".
create function deviation_proposal_day(p date) returns text language sql immutable as $$
  select to_char(p, 'Dy FMDD Mon YYYY')
$$;

-- Writes a proposal for every deadline missed on p_today (due before it, due on or after the 'since' day, not
-- met), once. Returns how many were new.
create function deviation_proposals_find(p_today date default signal_cairo_today())
returns int language plpgsql security definer set search_path = public as $$
declare
  v_since date := coalesce((select (value #>> '{}')::date from app_setting where key = 'deviation_proposals_since'),
                           p_today);
  v_new   int;
begin
  with missed as (
    -- The five-day clock to the EDA: a finding that concerns us, not reported, past its due day.
    select 'eda_clock'::text as kind, c.issue_id as id, c.day_zero::text as step, null::text as ref,
           c.ingredient_id, c.due,
           'Finding not reported to the EDA within five days' as title,
           format('The finding "%s"%s%s was due to the Egyptian Drug Authority on %s (five days from %s, the day '
                  'PHAROS showed it) and had not been reported by %s.',
                  c.title,
                  case when c.ingredient is not null then ' on ' || c.ingredient else '' end,
                  case when c.country is not null then ' (' || c.country || ')' else '' end,
                  deviation_proposal_day(c.due), deviation_proposal_day(c.day_zero),
                  deviation_proposal_day(p_today)) as description,
           true as safety, true as compliance, false as documents
      from eda_clock(null) c
     where c.clock in ('running', 'late') and c.due < p_today
    union all
    -- A signal whose current step is past its due day.
    select 'signal_step', s.id, s.stage::text, s.ref, s.ingredient_id, s.next_due,
           'Signal step not done on time',
           format('Signal %s "%s"%s: the %s step was due on %s and was not done by %s.',
                  s.ref, s.title,
                  case when s.ingredient is not null then ' (' || s.ingredient || ')' else '' end,
                  s.stage::text, deviation_proposal_day(s.next_due), deviation_proposal_day(p_today)),
           true, true, false
      from v_signal_table s
     where s.stage <> 'closed' and s.next_due < p_today
    union all
    -- A CAPA not done (or effective) by its due day. A new due day missed again is a new miss.
    select 'capa', c.id, c.due_on::text, c.ref, null::uuid, c.due_on,
           'CAPA not done by its due day',
           format('%s (from %s) was due on %s and was still %s on %s.',
                  c.ref,
                  case when c.deviation_id is not null then 'deviation ' || d.ref
                       else 'audit "' || a.title || '", observation ' || o.number end,
                  deviation_proposal_day(c.due_on),
                  case c.status when 'draft' then 'a draft' when 'approved' then 'approved, not started'
                                else 'in progress' end,
                  deviation_proposal_day(p_today)),
           false, true, false
      from capa c
      left join deviation d on d.id = c.deviation_id
      left join audit_observation o on o.id = c.observation_id
      left join audit a on a.id = o.audit_id
     where c.status not in ('done', 'effective') and c.due_on is not null and c.due_on < p_today
    union all
    -- A deadline of an audit (PV-SOP-022), as quality_audit_deadlines() counts it, past and not met.
    select 'audit_deadline', a.id, dl ->> 'key', a.title, null::uuid, (dl ->> 'due')::date,
           'Audit deadline missed',
           format('%s "%s": %s was due on %s (PV-SOP-022) and was not done by %s.',
                  case a.kind when 'internal' then 'Internal audit' else 'External audit' end, a.title,
                  case dl ->> 'key'
                    when 'plan' then 'the audit plan (two weeks before the visit)'
                    when 'rfi' then 'the answer to the request for information (72 hours)'
                    when 'review' then 'the QPPV review of the report'
                    when 'meeting' then 'the meeting with the responsible persons'
                    when 'draft' then 'the draft CAPA'
                    when 'approval' then 'the review and approval of all CAPAs'
                    when 'submission' then 'the submission of the CAPA'
                    else dl ->> 'key' end,
                  deviation_proposal_day((dl ->> 'due')::date), deviation_proposal_day(p_today)),
           false, true, false
      from audit a
      cross join lateral jsonb_array_elements(quality_audit_deadlines(a, p_today)) dl
     where a.status <> 'closed' and dl ->> 'state' = 'late'
  ), ins as (
    insert into deviation_proposal (source_kind, source_id, source_step, source_ref, ingredient_id, title,
                                    description, occurred_on, detected_on, patient_safety, regulatory_compliance,
                                    document_quality)
    select m.kind, m.id, coalesce(m.step, ''), m.ref, m.ingredient_id, m.title, m.description, m.due, p_today,
           m.safety, m.compliance, m.documents
      from missed m
     where m.due >= v_since and m.due < p_today
    on conflict (source_kind, source_id, source_step) do nothing
    returning 1
  )
  select count(*) into v_new from ins;
  return v_new;
end $$;

-- ───────────────────────────── 4. what the tab reads, and her two decisions ─────────────────────────────
-- [{id, source_kind, source_ref, ingredient_id, title, description, occurred_on, detected_on, flags…, status,
--   dismissed_reason, deviation_id, deviation_ref, decided_by (a name), decided_at}]: the proposed ones first
--   (oldest miss first), then the decided ones, newest decision first.
create function deviation_proposals() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the quality records.' using errcode = '42501';
  end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'id', p.id, 'source_kind', p.source_kind, 'source_ref', p.source_ref, 'ingredient_id', p.ingredient_id,
             'title', p.title, 'description', p.description, 'occurred_on', p.occurred_on,
             'detected_on', p.detected_on, 'patient_safety', p.patient_safety,
             'regulatory_compliance', p.regulatory_compliance, 'document_quality', p.document_quality,
             'status', p.status, 'dismissed_reason', p.dismissed_reason, 'deviation_id', p.deviation_id,
             'deviation_ref', d.ref, 'decided_by', pd.full_name, 'decided_at', p.decided_at)
           order by (p.status = 'proposed') desc,
                    case when p.status = 'proposed' then p.occurred_on end,
                    p.decided_at desc nulls last, p.created_at)
      from deviation_proposal p
      left join deviation d on d.id = p.deviation_id
      left join person pd on pd.id = p.decided_by), '[]'::jsonb);
end $$;

-- Record a proposal as a deviation: the deviation is opened through deviation_open_as() (its D-number, its
-- history), with what she wrote — the proposal's words are only the starting point.
create function deviation_proposal_confirm(p_id uuid, p_title text, p_description text, p_occurred_on date,
                                           p_detected_on date, p_patient_safety boolean default false,
                                           p_regulatory_compliance boolean default false,
                                           p_document_quality boolean default false)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_status text;
  v_dev    uuid;
begin
  select status into v_status from deviation_proposal where id = p_id for update;
  if v_status is null then
    raise exception 'That proposed deviation does not exist.' using errcode = '22023';
  end if;
  if v_status <> 'proposed' then
    raise exception 'STALE_QUALITY: this proposal was already %.', v_status
      using errcode = 'PH409', hint = 'Reload the record and look again.';
  end if;
  v_dev := deviation_open_as(v_person, signal_cairo_today(), p_title, p_description, p_occurred_on, p_detected_on,
                             p_patient_safety, p_regulatory_compliance, p_document_quality);
  update deviation_proposal
     set status = 'confirmed', deviation_id = v_dev, decided_by = v_person, decided_at = now()
   where id = p_id;
  return v_dev;
end $$;

-- Dismiss a proposal: the reason is required and kept; the same missed deadline is never proposed again.
create function deviation_proposal_dismiss(p_id uuid, p_reason text)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_status text;
begin
  select status into v_status from deviation_proposal where id = p_id for update;
  if v_status is null then
    raise exception 'That proposed deviation does not exist.' using errcode = '22023';
  end if;
  if v_status <> 'proposed' then
    raise exception 'STALE_QUALITY: this proposal was already %.', v_status
      using errcode = 'PH409', hint = 'Reload the record and look again.';
  end if;
  update deviation_proposal
     set status = 'dismissed', dismissed_reason = quality_need_comment(p_reason), decided_by = v_person,
         decided_at = now()
   where id = p_id;
  return 'dismissed';
end $$;

-- ───────────────────────────── 5. grants ─────────────────────────────
revoke all on function deviation_proposal_day(date), deviation_proposals_find(date) from public, anon, authenticated;
revoke all on function deviation_proposals(),
  deviation_proposal_confirm(uuid, text, text, date, date, boolean, boolean, boolean),
  deviation_proposal_dismiss(uuid, text)
  from public, anon;
grant execute on function deviation_proposals(),
  deviation_proposal_confirm(uuid, text, text, date, date, boolean, boolean, boolean),
  deviation_proposal_dismiss(uuid, text)
  to authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function deviation_proposal_day(date), deviation_proposals_find(date),
      deviation_proposals(), deviation_proposal_confirm(uuid, text, text, date, date, boolean, boolean, boolean),
      deviation_proposal_dismiss(uuid, text) from service_role';
  end if;
end $$;
