-- PHAROS — Quality: deviations, audits and one CAPA plan both feed (2026-11-09).
--
-- Dr Sama's three SOPs, in her own summary: an observation that needs a CAPA comes from one of two places — a
-- mistake that happened (a deviation, PV-SOP-021) or an observation from an audit, internal or external
-- (PV-SOP-022). Both end in the same CAPA plan. The QMS SOP (PV-SOP-024) is only an overview.
--
-- 1. deviation (form PV-FM-009): an unplanned event that puts patient safety or product quality at risk, or breaks
--    an SOP. Numbered D000/0000: D, a three-digit serial, slash, the year it was recorded (D001/2026); the serial
--    restarts each year and is taken under an advisory lock. QA sets its level: 1 = no impact on patient safety
--    or compliance, 2 = may affect compliance, 3 = impact on patient safety. The six investigation answers, the
--    root cause and the QA Manager's satisfactory / not satisfactory are kept on the row.
--    open → investigating → capa → approved → closed. Not satisfactory sends it back to investigating. It closes
--    only when every CAPA of it is effective.
-- 2. audit (plan PV-FM-011, report PV-FM-012): internal (the PV department, last quarter of each year) or
--    external (another marketing authorisation holder under the safety data exchange agreement). Day zero is the
--    day the report was received: review +1 day, meeting +2, draft CAPA +10, approval +12, submission +14. The day
--    each was done is kept on the row (reviewed_on … capa_submitted_on), so each deadline reads due, late or done.
--    A request for information is answered within 72 hours (+3 days). planned → report_received →
--    capa_submitted → closed; closed needs the closure confirmation day and every CAPA of it effective.
-- 3. audit_observation: one finding of an audit, numbered within it, graded critical / major / minor, assigned
--    to a stakeholder (a PHAROS person, or someone outside PHAROS by name), with its root cause.
-- 4. capa (forms PV-FM-010 and PV-FM-013): CAPA-001/2026, serial per year like the deviations. Its source is
--    exactly one deviation or one audit observation. draft → approved → in_progress → done → effective;
--    not effective sends it back to in_progress. Approved needs an owner and a due day; done needs the evidence.
-- 5. quality_event: the history of all four, written by the functions below only, append-only (an update,
--    delete or truncate is refused for every role, the owner included). Nothing is ever deleted: a correction
--    is a new history row with what changed (before / after).
-- 6. Writes: only a reviewer or an administrator, only through the functions (no insert, update or delete
--    from the app). A step names the status the person saw; when the row moved meanwhile it is refused with
--    PH409 STALE_QUALITY, as signal_take_step does. A judgement (a level, an approval, effective or not,
--    closing) needs a comment. Every member of the team reads everything, through quality_state().
-- The service key holds no right on any of it, as 0048 did for report_request.

-- ───────────────────────────── 1. deviations ─────────────────────────────
create table deviation (
  id                     uuid primary key default gen_random_uuid(),
  year                   int not null check (year between 2000 and 2999),
  serial                 int not null check (serial between 1 and 999),
  ref                    text generated always as ('D' || lpad(serial::text, 3, '0') || '/' || year::text) stored,
  title                  text not null check (length(trim(title)) > 0),
  description            text not null check (length(trim(description)) > 0),
  occurred_on            date,
  detected_on            date not null,
  level                  smallint check (level in (1, 2, 3)),
  patient_safety         boolean not null default false,
  regulatory_compliance  boolean not null default false,
  document_quality       boolean not null default false,
  -- the six investigation questions of PV-SOP-021
  inv_cause              text,   -- What was the cause?
  inv_people_time        text,   -- Who was involved, the time and the duration?
  inv_reoccur            text,   -- Could it reoccur?
  inv_similar            text,   -- Have similar deviations occurred in the past?
  inv_other_impact       text,   -- Any impact on other products or processes?
  inv_training           text,   -- Training status of the people involved?
  root_cause             text,
  qa_satisfactory        boolean,
  status                 text not null default 'open'
                         check (status in ('open', 'investigating', 'capa', 'approved', 'closed')),
  created_by             uuid not null references person(id),
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  approved_by            uuid references person(id),
  approved_at            timestamptz,
  closed_by              uuid references person(id),
  closed_at              timestamptz,
  unique (year, serial),
  check (occurred_on is null or occurred_on <= detected_on),
  check (status <> 'closed' or closed_at is not null),
  check (status not in ('approved', 'closed') or (approved_at is not null and coalesce(qa_satisfactory, false)))
);
comment on table deviation is
  'A deviation (PV-SOP-021, form PV-FM-009), numbered D001/2026; written only through the deviation_* functions (0107).';

-- ───────────────────────────── 2. audits ─────────────────────────────
create table audit (
  id                    uuid primary key default gen_random_uuid(),
  kind                  text not null check (kind in ('internal', 'external')),
  title                 text not null check (length(trim(title)) > 0),
  auditor               text not null check (length(trim(auditor)) > 0),  -- the organisation (the MAH for external)
  lead_auditor          text,
  planned_on            date,          -- the day the audit is planned for
  plan_sent_on          date,          -- internal: the audit plan (PV-FM-011) sent to the QPPV, two weeks before
  visit_from            date,
  visit_to              date,
  rfi_received_on       date,          -- a request for information: answered within 72 hours
  rfi_answered_on       date,
  report_received_on    date,          -- day zero (PV-FM-012)
  reviewed_on           date,          -- QPPV review: day 1
  meeting_on            date,          -- meeting with the responsible persons: day 2
  capa_drafted_on       date,          -- draft CAPA: day 10
  capa_approved_on      date,          -- every CAPA reviewed and approved: day 12
  capa_submitted_on     date,          -- submitted (internal: the reporting system; external: emailed): day 14
  final_report_on       date,          -- the final report (observations and agreed CAPA) received
  closure_confirmed_on  date,          -- the lead auditor's closure confirmation (email or close-out memo)
  status                text not null default 'planned'
                        check (status in ('planned', 'report_received', 'capa_submitted', 'closed')),
  created_by            uuid not null references person(id),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check (visit_from is null or visit_to is null or visit_from <= visit_to),
  check (status = 'planned' or report_received_on is not null),
  check (status not in ('capa_submitted', 'closed') or capa_submitted_on is not null),
  check (status <> 'closed' or closure_confirmed_on is not null)
);
comment on table audit is
  'An internal or external PV audit (PV-SOP-022); confidential to the team; written only through the audit_* functions (0107).';

create table audit_observation (
  id              uuid primary key default gen_random_uuid(),
  audit_id        uuid not null references audit(id),
  number          int not null check (number > 0),
  text            text not null check (length(trim(text)) > 0),
  grade           text not null check (grade in ('critical', 'major', 'minor')),
  assigned_to     uuid references person(id),
  assigned_other  text,            -- a stakeholder outside PHAROS: name and department
  root_cause      text,
  created_by      uuid not null references person(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (audit_id, number)
);

-- ───────────────────────────── 3. the CAPA plan ─────────────────────────────
create table capa (
  id                 uuid primary key default gen_random_uuid(),
  year               int not null check (year between 2000 and 2999),
  serial             int not null check (serial between 1 and 999),
  ref                text generated always as ('CAPA-' || lpad(serial::text, 3, '0') || '/' || year::text) stored,
  deviation_id       uuid references deviation(id),
  observation_id     uuid references audit_observation(id),
  corrective_action  text,
  preventive_action  text,
  owner_id           uuid references person(id),
  owner_other        text,         -- an owner outside PHAROS: name and department
  due_on             date,
  status             text not null default 'draft'
                     check (status in ('draft', 'approved', 'in_progress', 'done', 'effective')),
  evidence           text,         -- what was done: a document reference or a link
  done_on            date,
  verified_by        uuid references person(id),
  verified_at        timestamptz,
  created_by         uuid not null references person(id),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (year, serial),
  -- exactly one source: a deviation or an audit observation
  constraint capa_one_source check (num_nonnulls(deviation_id, observation_id) = 1),
  check (length(trim(coalesce(corrective_action, ''))) > 0 or length(trim(coalesce(preventive_action, ''))) > 0),
  check (status = 'draft' or (due_on is not null and (owner_id is not null or length(trim(coalesce(owner_other, ''))) > 0))),
  check (status not in ('done', 'effective') or (done_on is not null and length(trim(coalesce(evidence, ''))) > 0)),
  check (status <> 'effective' or (verified_by is not null and verified_at is not null))
);
comment on table capa is
  'A CAPA (PV-FM-010, PV-FM-013), CAPA-001/2026, from exactly one deviation or one audit observation (0107).';
create index on capa (deviation_id) where deviation_id is not null;
create index on capa (observation_id) where observation_id is not null;

-- ───────────────────────────── 4. the history ─────────────────────────────
create table quality_event (
  id           bigint generated always as identity primary key,
  record_kind  text not null check (record_kind in ('deviation', 'audit', 'observation', 'capa')),
  record_id    uuid not null,
  step         text not null,
  from_status  text,
  to_status    text,
  comment      text,
  before       jsonb,
  after        jsonb,
  person_id    uuid not null references person(id),
  at           timestamptz not null default now()
);
create index on quality_event (record_kind, record_id, at);
create index on quality_event (at);

create function quality_event_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'quality_event is append-only';
end $$;
create trigger quality_event_no_update before update or delete on quality_event
  for each row execute function quality_event_immutable();
create trigger quality_event_no_truncate before truncate on quality_event
  for each statement execute function quality_event_immutable();
revoke all on function quality_event_immutable() from public, anon, authenticated;

do $$
declare t text;
begin
  foreach t in array array['deviation', 'audit', 'audit_observation', 'capa', 'quality_event'] loop
    execute format('create trigger audit_%1$s after insert or update or delete on %1$s
                    for each row execute function audit_row()', t);
    execute format('alter table %1$s enable row level security', t);
    execute format('create policy %1$s_read on %1$s for select to authenticated using (my_role() is not null)', t);
    execute format('revoke all on %1$s from public, anon', t);
    execute format('revoke insert, update, delete, truncate on %1$s from authenticated', t);
    if exists (select 1 from pg_roles where rolname = 'service_role') then
      execute format('revoke all on %1$s from service_role', t);
    end if;
  end loop;
end $$;
-- No write policies: only the functions below write, as the signed-in person, at the database's time.

-- ───────────────────────────── 5. helpers (granted to nobody) ─────────────────────────────
create function quality_require_writer() returns uuid language plpgsql stable security definer
set search_path = public as $$
declare v_person uuid := my_person_id();
begin
  if v_person is null or my_role() is null or my_role() not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can change the quality records.' using errcode = '42501';
  end if;
  return v_person;
end $$;

create function quality_stale(p_expected text, p_now text) returns void language plpgsql as $$
begin
  if p_expected is distinct from p_now then
    raise exception 'STALE_QUALITY: someone else changed this record a moment ago; it is now %.', p_now
      using errcode = 'PH409', hint = 'Reload the record and look again.';
  end if;
end $$;

-- What changed between two rows: the keys whose value differs, before and after (updated_at left out).
create function quality_changed(p_old jsonb, p_new jsonb, out before jsonb, out after jsonb)
language sql immutable as $$
  select coalesce(jsonb_object_agg(t.k, p_old -> t.k), '{}'::jsonb),
         coalesce(jsonb_object_agg(t.k, p_new -> t.k), '{}'::jsonb)
    from jsonb_object_keys(p_new) as t(k)
   where t.k <> 'updated_at' and (p_old -> t.k) is distinct from (p_new -> t.k)
$$;

create function quality_log(p_kind text, p_id uuid, p_step text, p_from text, p_to text, p_comment text,
                            p_before jsonb, p_after jsonb, p_person uuid)
returns void language sql security definer set search_path = public as $$
  insert into quality_event (record_kind, record_id, step, from_status, to_status, comment, before, after, person_id)
  values (p_kind, p_id, p_step, p_from, p_to, nullif(trim(p_comment), ''), p_before, p_after, p_person)
$$;

create function quality_need_comment(p_comment text) returns text language plpgsql as $$
begin
  if length(trim(coalesce(p_comment, ''))) = 0 then
    raise exception 'This step needs a comment for the record.' using errcode = '22023';
  end if;
  return trim(p_comment);
end $$;

-- A day something was done: not in the future (Cairo).
create function quality_past_day(p_day date, p_what text) returns date language plpgsql stable as $$
begin
  if p_day is not null and p_day > signal_cairo_today() then
    raise exception '% cannot be in the future.', p_what using errcode = '22023';
  end if;
  return p_day;
end $$;

-- An owner or a stakeholder: a PHAROS person who exists.
create function quality_person(p_person uuid) returns uuid language plpgsql stable security definer
set search_path = public as $$
begin
  if p_person is not null and not exists (select 1 from person where id = p_person) then
    raise exception 'That person is not in PHAROS.' using errcode = '22023';
  end if;
  return p_person;
end $$;

-- A deadline: its state from the Cairo day. done, late (past and not done), soon (0–2 days left), running.
create function quality_due(p_due date, p_done date, p_today date) returns jsonb language sql immutable as $$
  select case when p_due is null then null else jsonb_build_object(
    'due', p_due,
    'done_on', p_done,
    'days_left', p_due - p_today,
    'state', case when p_done is not null then 'done'
                  when p_due < p_today then 'late'
                  when p_due - p_today <= 2 then 'soon'
                  else 'running' end) end
$$;

-- The next serial of a year (D… or CAPA-…), under a lock so two people never take the same number.
create function quality_next_serial(p_kind text, p_year int) returns int language plpgsql security definer
set search_path = public as $$
declare v_next int;
begin
  perform pg_advisory_xact_lock(hashtext('quality_serial:' || p_kind), p_year);
  if p_kind = 'deviation' then
    select coalesce(max(serial), 0) + 1 into v_next from deviation where year = p_year;
  else
    select coalesce(max(serial), 0) + 1 into v_next from capa where year = p_year;
  end if;
  if v_next > 999 then
    raise exception 'The numbers of % are full: 999 a year.', p_year using errcode = '22023';
  end if;
  return v_next;
end $$;

-- ───────────────────────────── 6. deviations: the functions ─────────────────────────────
-- deviation_open_as: the one code path that records a deviation; p_on is the day it is recorded (its number's
-- year). Granted to nobody: deviation_open() calls it for the signed-in reviewer or administrator, today.
create function deviation_open_as(p_person uuid, p_on date, p_title text, p_description text, p_occurred_on date,
                                  p_detected_on date, p_patient_safety boolean default false,
                                  p_regulatory_compliance boolean default false,
                                  p_document_quality boolean default false)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_year int := extract(year from p_on)::int;
  v_id   uuid;
begin
  if length(trim(coalesce(p_title, ''))) = 0 then
    raise exception 'A deviation needs a title.' using errcode = '22023';
  end if;
  if length(trim(coalesce(p_description, ''))) = 0 then
    raise exception 'Describe the deviation in full.' using errcode = '22023';
  end if;
  if p_detected_on is null then
    raise exception 'Give the day it was detected.' using errcode = '22023';
  end if;
  if p_detected_on > p_on or (p_occurred_on is not null and p_occurred_on > p_detected_on) then
    raise exception 'It happened on or before the day it was detected, and both have passed.' using errcode = '22023';
  end if;
  insert into deviation (year, serial, title, description, occurred_on, detected_on, patient_safety,
                         regulatory_compliance, document_quality, created_by)
  values (v_year, quality_next_serial('deviation', v_year), trim(p_title), trim(p_description), p_occurred_on,
          p_detected_on, coalesce(p_patient_safety, false), coalesce(p_regulatory_compliance, false),
          coalesce(p_document_quality, false), p_person)
  returning id into v_id;
  perform quality_log('deviation', v_id, 'opened', null, 'open', null, null, null, p_person);
  return v_id;
end $$;

create function deviation_open(p_title text, p_description text, p_occurred_on date, p_detected_on date,
                               p_patient_safety boolean default false, p_regulatory_compliance boolean default false,
                               p_document_quality boolean default false)
returns uuid language plpgsql security definer set search_path = public as $$
begin
  return deviation_open_as(quality_require_writer(), signal_cairo_today(), p_title, p_description, p_occurred_on,
                           p_detected_on, p_patient_safety, p_regulatory_compliance, p_document_quality);
end $$;

-- p: any of title, description, occurred_on, detected_on, patient_safety, regulatory_compliance,
-- document_quality, inv_cause, inv_people_time, inv_reoccur, inv_similar, inv_other_impact, inv_training,
-- root_cause. Only the keys given change; a closed deviation is not changed.
create function deviation_update(p_id uuid, p_expected text, p jsonb, p_comment text default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_old    deviation%rowtype;
  v_new    deviation%rowtype;
  v_diff   record;
begin
  select * into v_old from deviation where id = p_id for update;
  if v_old.id is null then raise exception 'That deviation does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_old.status);
  if v_old.status = 'closed' then
    raise exception 'A closed deviation is kept as it is.' using errcode = '22023';
  end if;
  p := coalesce(p, '{}'::jsonb);
  if (p ? 'title' and length(trim(coalesce(p ->> 'title', ''))) = 0)
     or (p ? 'description' and length(trim(coalesce(p ->> 'description', ''))) = 0)
     or (p ? 'detected_on' and nullif(p ->> 'detected_on', '') is null) then
    raise exception 'A deviation keeps its title, its description and the day it was detected.' using errcode = '22023';
  end if;
  update deviation set
    title                 = case when p ? 'title' then trim(p ->> 'title') else title end,
    description           = case when p ? 'description' then trim(p ->> 'description') else description end,
    occurred_on           = case when p ? 'occurred_on' then nullif(p ->> 'occurred_on', '')::date else occurred_on end,
    detected_on           = case when p ? 'detected_on'
                                 then quality_past_day((p ->> 'detected_on')::date, 'The day it was detected')
                                 else detected_on end,
    patient_safety        = case when p ? 'patient_safety' then coalesce((p ->> 'patient_safety')::boolean, false) else patient_safety end,
    regulatory_compliance = case when p ? 'regulatory_compliance' then coalesce((p ->> 'regulatory_compliance')::boolean, false) else regulatory_compliance end,
    document_quality      = case when p ? 'document_quality' then coalesce((p ->> 'document_quality')::boolean, false) else document_quality end,
    inv_cause             = case when p ? 'inv_cause' then nullif(trim(p ->> 'inv_cause'), '') else inv_cause end,
    inv_people_time       = case when p ? 'inv_people_time' then nullif(trim(p ->> 'inv_people_time'), '') else inv_people_time end,
    inv_reoccur           = case when p ? 'inv_reoccur' then nullif(trim(p ->> 'inv_reoccur'), '') else inv_reoccur end,
    inv_similar           = case when p ? 'inv_similar' then nullif(trim(p ->> 'inv_similar'), '') else inv_similar end,
    inv_other_impact      = case when p ? 'inv_other_impact' then nullif(trim(p ->> 'inv_other_impact'), '') else inv_other_impact end,
    inv_training          = case when p ? 'inv_training' then nullif(trim(p ->> 'inv_training'), '') else inv_training end,
    root_cause            = case when p ? 'root_cause' then nullif(trim(p ->> 'root_cause'), '') else root_cause end,
    updated_at            = now()
  where id = p_id
  returning * into v_new;
  select * into v_diff from quality_changed(to_jsonb(v_old), to_jsonb(v_new));
  if v_diff.after = '{}'::jsonb then
    raise exception 'Nothing changed.' using errcode = '22023';
  end if;
  perform quality_log('deviation', p_id, 'updated', v_old.status, v_old.status, p_comment, v_diff.before, v_diff.after, v_person);
  return v_new.status;
end $$;

-- QA sets the level: 1, 2 or 3, with the reason.
create function deviation_set_level(p_id uuid, p_expected text, p_level int, p_comment text)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person  uuid := quality_require_writer();
  v_old     deviation%rowtype;
  v_comment text;
begin
  select * into v_old from deviation where id = p_id for update;
  if v_old.id is null then raise exception 'That deviation does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_old.status);
  if v_old.status = 'closed' then
    raise exception 'A closed deviation keeps its level.' using errcode = '22023';
  end if;
  if p_level is null or p_level not in (1, 2, 3) then
    raise exception 'Choose level 1, 2 or 3.' using errcode = '22023';
  end if;
  if p_level = v_old.level then
    raise exception 'The deviation is already at level %.', p_level using errcode = '22023';
  end if;
  v_comment := quality_need_comment(p_comment);
  update deviation set level = p_level, updated_at = now() where id = p_id;
  perform quality_log('deviation', p_id, 'level_set', v_old.status, v_old.status, v_comment,
                      jsonb_build_object('level', v_old.level), jsonb_build_object('level', p_level), v_person);
  return v_old.status;
end $$;

-- p_to: investigating (from open; or from capa when the QA Manager is not satisfied), capa (the root cause and
-- the level are known), approved (from capa, with p_satisfactory: true approves, false sends it back to
-- investigating), closed (from approved, when every CAPA of it is effective). Answers the new status.
create function deviation_step(p_id uuid, p_to text, p_expected text, p_comment text default null,
                               p_satisfactory boolean default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_d      deviation%rowtype;
  v_to     text := p_to;
begin
  select * into v_d from deviation where id = p_id for update;
  if v_d.id is null then raise exception 'That deviation does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_d.status);
  case p_to
    when 'investigating' then
      if v_d.status <> 'open' then
        raise exception 'Only an open deviation starts its investigation.' using errcode = '22023';
      end if;
      update deviation set status = 'investigating', updated_at = now() where id = p_id;
    when 'capa' then
      if v_d.status <> 'investigating' then
        raise exception 'Only a deviation under investigation moves to its CAPA.' using errcode = '22023';
      end if;
      if v_d.level is null then
        raise exception 'QA sets the level first.' using errcode = '22023';
      end if;
      if length(trim(coalesce(v_d.root_cause, ''))) = 0 then
        raise exception 'Give the root cause first.' using errcode = '22023';
      end if;
      update deviation set status = 'capa', updated_at = now() where id = p_id;
    when 'approved' then
      if v_d.status <> 'capa' then
        raise exception 'Only a deviation with its CAPA planned goes to the QA Manager.' using errcode = '22023';
      end if;
      if p_satisfactory is null then
        raise exception 'Say whether the investigation is satisfactory.' using errcode = '22023';
      end if;
      perform quality_need_comment(p_comment);
      if p_satisfactory then
        if not exists (select 1 from capa where deviation_id = p_id) then
          raise exception 'Add its CAPA first.' using errcode = '22023';
        end if;
        update deviation set status = 'approved', qa_satisfactory = true, approved_by = v_person,
                             approved_at = now(), updated_at = now() where id = p_id;
      else
        v_to := 'investigating';
        update deviation set status = 'investigating', qa_satisfactory = false, updated_at = now() where id = p_id;
      end if;
    when 'closed' then
      if v_d.status <> 'approved' then
        raise exception 'Only an approved deviation can be closed.' using errcode = '22023';
      end if;
      perform quality_need_comment(p_comment);
      if exists (select 1 from capa where deviation_id = p_id and status <> 'effective') then
        raise exception 'A CAPA of this deviation is still open: it closes when every CAPA is effective.'
          using errcode = '22023';
      end if;
      update deviation set status = 'closed', closed_by = v_person, closed_at = now(), updated_at = now() where id = p_id;
    else
      raise exception 'That is not a step of a deviation.' using errcode = '22023';
  end case;
  perform quality_log('deviation', p_id, case when p_to = 'approved' and not p_satisfactory then 'not_satisfactory'
                                              else p_to end,
                      v_d.status, v_to, p_comment,
                      case when p_to = 'approved' then jsonb_build_object('qa_satisfactory', v_d.qa_satisfactory) end,
                      case when p_to = 'approved' then jsonb_build_object('qa_satisfactory', p_satisfactory) end,
                      v_person);
  return v_to;
end $$;

-- ───────────────────────────── 7. audits: the functions ─────────────────────────────
create function audit_open(p_kind text, p_title text, p_auditor text, p_lead_auditor text default null,
                           p_planned_on date default null, p_visit_from date default null, p_visit_to date default null,
                           p_report_received_on date default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_status text := case when p_report_received_on is null then 'planned' else 'report_received' end;
  v_id     uuid;
begin
  if p_kind is null or p_kind not in ('internal', 'external') then
    raise exception 'Choose an internal or an external audit.' using errcode = '22023';
  end if;
  if length(trim(coalesce(p_title, ''))) = 0 then
    raise exception 'An audit needs a title.' using errcode = '22023';
  end if;
  if length(trim(coalesce(p_auditor, ''))) = 0 then
    raise exception 'Name the auditor (the organisation; the marketing authorisation holder for an external audit).'
      using errcode = '22023';
  end if;
  if p_visit_from is not null and p_visit_to is not null and p_visit_to < p_visit_from then
    raise exception 'The visit ends on or after its first day.' using errcode = '22023';
  end if;
  perform quality_past_day(p_report_received_on, 'The day the report was received');
  insert into audit (kind, title, auditor, lead_auditor, planned_on, visit_from, visit_to, report_received_on,
                     status, created_by)
  values (p_kind, trim(p_title), trim(p_auditor), nullif(trim(p_lead_auditor), ''), p_planned_on, p_visit_from,
          p_visit_to, p_report_received_on, v_status, v_person)
  returning id into v_id;
  perform quality_log('audit', v_id, 'opened', null, v_status, null, null, null, v_person);
  return v_id;
end $$;

-- p: any of title, auditor, lead_auditor, planned_on, plan_sent_on, visit_from, visit_to, rfi_received_on,
-- rfi_answered_on, report_received_on, reviewed_on, meeting_on, capa_drafted_on, capa_approved_on,
-- capa_submitted_on, final_report_on, closure_confirmed_on. A day something was done is not in the future, and
-- a step of the report is on or after the day the report was received. A closed audit is not changed.
create function audit_update(p_id uuid, p_expected text, p jsonb, p_comment text default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_old    audit%rowtype;
  v_new    audit%rowtype;
  v_diff   record;
  v_key    text;
begin
  select * into v_old from audit where id = p_id for update;
  if v_old.id is null then raise exception 'That audit does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_old.status);
  if v_old.status = 'closed' then
    raise exception 'A closed audit is kept as it is.' using errcode = '22023';
  end if;
  p := coalesce(p, '{}'::jsonb);
  if (p ? 'title' and length(trim(coalesce(p ->> 'title', ''))) = 0)
     or (p ? 'auditor' and length(trim(coalesce(p ->> 'auditor', ''))) = 0) then
    raise exception 'An audit keeps its title and its auditor.' using errcode = '22023';
  end if;
  foreach v_key in array array['plan_sent_on', 'rfi_received_on', 'rfi_answered_on', 'report_received_on',
                               'reviewed_on', 'meeting_on', 'capa_drafted_on', 'capa_approved_on',
                               'capa_submitted_on', 'final_report_on', 'closure_confirmed_on'] loop
    if p ? v_key then
      perform quality_past_day(nullif(p ->> v_key, '')::date, 'A day something was done');
    end if;
  end loop;
  if v_old.status <> 'planned' and p ? 'report_received_on' and nullif(p ->> 'report_received_on', '') is null then
    raise exception 'The report was received: its day stays.' using errcode = '22023';
  end if;
  update audit set
    title                = case when p ? 'title' then trim(p ->> 'title') else title end,
    auditor              = case when p ? 'auditor' then trim(p ->> 'auditor') else auditor end,
    lead_auditor         = case when p ? 'lead_auditor' then nullif(trim(p ->> 'lead_auditor'), '') else lead_auditor end,
    planned_on           = case when p ? 'planned_on' then nullif(p ->> 'planned_on', '')::date else planned_on end,
    plan_sent_on         = case when p ? 'plan_sent_on' then nullif(p ->> 'plan_sent_on', '')::date else plan_sent_on end,
    visit_from           = case when p ? 'visit_from' then nullif(p ->> 'visit_from', '')::date else visit_from end,
    visit_to             = case when p ? 'visit_to' then nullif(p ->> 'visit_to', '')::date else visit_to end,
    rfi_received_on      = case when p ? 'rfi_received_on' then nullif(p ->> 'rfi_received_on', '')::date else rfi_received_on end,
    rfi_answered_on      = case when p ? 'rfi_answered_on' then nullif(p ->> 'rfi_answered_on', '')::date else rfi_answered_on end,
    report_received_on   = case when p ? 'report_received_on' then nullif(p ->> 'report_received_on', '')::date else report_received_on end,
    reviewed_on          = case when p ? 'reviewed_on' then nullif(p ->> 'reviewed_on', '')::date else reviewed_on end,
    meeting_on           = case when p ? 'meeting_on' then nullif(p ->> 'meeting_on', '')::date else meeting_on end,
    capa_drafted_on      = case when p ? 'capa_drafted_on' then nullif(p ->> 'capa_drafted_on', '')::date else capa_drafted_on end,
    capa_approved_on     = case when p ? 'capa_approved_on' then nullif(p ->> 'capa_approved_on', '')::date else capa_approved_on end,
    capa_submitted_on    = case when p ? 'capa_submitted_on' then nullif(p ->> 'capa_submitted_on', '')::date else capa_submitted_on end,
    final_report_on      = case when p ? 'final_report_on' then nullif(p ->> 'final_report_on', '')::date else final_report_on end,
    closure_confirmed_on = case when p ? 'closure_confirmed_on' then nullif(p ->> 'closure_confirmed_on', '')::date else closure_confirmed_on end,
    updated_at           = now()
  where id = p_id
  returning * into v_new;
  if least(v_new.reviewed_on, v_new.meeting_on, v_new.capa_drafted_on, v_new.capa_approved_on,
           v_new.capa_submitted_on, v_new.final_report_on, v_new.closure_confirmed_on) < v_new.report_received_on
     or (v_new.report_received_on is null
         and coalesce(v_new.reviewed_on, v_new.meeting_on, v_new.capa_drafted_on, v_new.capa_approved_on,
                      v_new.capa_submitted_on, v_new.final_report_on, v_new.closure_confirmed_on) is not null) then
    raise exception 'The steps after the report are on or after the day the report was received.' using errcode = '22023';
  end if;
  if v_new.rfi_answered_on < v_new.rfi_received_on
     or (v_new.rfi_answered_on is not null and v_new.rfi_received_on is null) then
    raise exception 'A request for information is answered on or after the day it was received.' using errcode = '22023';
  end if;
  if v_new.visit_from is not null and v_new.visit_to is not null and v_new.visit_to < v_new.visit_from then
    raise exception 'The visit ends on or after its first day.' using errcode = '22023';
  end if;
  select * into v_diff from quality_changed(to_jsonb(v_old), to_jsonb(v_new));
  if v_diff.after = '{}'::jsonb then
    raise exception 'Nothing changed.' using errcode = '22023';
  end if;
  perform quality_log('audit', p_id, 'updated', v_old.status, v_old.status, p_comment, v_diff.before, v_diff.after, v_person);
  return v_new.status;
end $$;

-- p_to: report_received (from planned; p_on the day the report was received, unless already given),
-- capa_submitted (from report_received; p_on the day submitted, today when not given), closed (from
-- capa_submitted; p_on the closure confirmation day unless already given; every CAPA of it effective).
create function audit_step(p_id uuid, p_to text, p_expected text, p_comment text default null, p_on date default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_a      audit%rowtype;
  v_on     date := quality_past_day(p_on, 'The day');
begin
  select * into v_a from audit where id = p_id for update;
  if v_a.id is null then raise exception 'That audit does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_a.status);
  case p_to
    when 'report_received' then
      if v_a.status <> 'planned' then
        raise exception 'Only a planned audit receives its report.' using errcode = '22023';
      end if;
      v_on := coalesce(v_on, v_a.report_received_on);
      if v_on is null then
        raise exception 'Give the day the report was received: the deadlines count from it.' using errcode = '22023';
      end if;
      update audit set status = 'report_received', report_received_on = v_on, updated_at = now() where id = p_id;
    when 'capa_submitted' then
      if v_a.status <> 'report_received' then
        raise exception 'Only an audit with its report received submits its CAPA.' using errcode = '22023';
      end if;
      v_on := coalesce(v_on, v_a.capa_submitted_on, signal_cairo_today());
      if v_on < v_a.report_received_on then
        raise exception 'The CAPA is submitted on or after the day the report was received.' using errcode = '22023';
      end if;
      update audit set status = 'capa_submitted', capa_submitted_on = v_on, updated_at = now() where id = p_id;
    when 'closed' then
      if v_a.status <> 'capa_submitted' then
        raise exception 'Only an audit whose CAPA was submitted can be closed.' using errcode = '22023';
      end if;
      perform quality_need_comment(p_comment);
      v_on := coalesce(v_on, v_a.closure_confirmed_on);
      if v_on is null then
        raise exception 'Give the day the lead auditor confirmed the closure.' using errcode = '22023';
      end if;
      if exists (select 1 from capa c join audit_observation o on o.id = c.observation_id
                  where o.audit_id = p_id and c.status <> 'effective') then
        raise exception 'A CAPA of this audit is still open: it closes when every CAPA is effective.'
          using errcode = '22023';
      end if;
      update audit set status = 'closed', closure_confirmed_on = v_on, updated_at = now() where id = p_id;
    else
      raise exception 'That is not a step of an audit.' using errcode = '22023';
  end case;
  perform quality_log('audit', p_id, p_to, v_a.status, p_to, p_comment, null,
                      case when v_on is not null then jsonb_build_object('on', v_on) end, v_person);
  return p_to;
end $$;

create function audit_add_observation(p_audit uuid, p_text text, p_grade text, p_assigned_to uuid default null,
                                      p_assigned_other text default null, p_root_cause text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_a      audit%rowtype;
  v_id     uuid;
  v_n      int;
begin
  select * into v_a from audit where id = p_audit for update;
  if v_a.id is null then raise exception 'That audit does not exist.' using errcode = '22023'; end if;
  if v_a.status = 'closed' then
    raise exception 'A closed audit takes no new observation.' using errcode = '22023';
  end if;
  if length(trim(coalesce(p_text, ''))) = 0 then
    raise exception 'Write the observation.' using errcode = '22023';
  end if;
  if p_grade is null or p_grade not in ('critical', 'major', 'minor') then
    raise exception 'Grade it critical, major or minor.' using errcode = '22023';
  end if;
  select coalesce(max(number), 0) + 1 into v_n from audit_observation where audit_id = p_audit;
  insert into audit_observation (audit_id, number, text, grade, assigned_to, assigned_other, root_cause, created_by)
  values (p_audit, v_n, trim(p_text), p_grade, quality_person(p_assigned_to), nullif(trim(p_assigned_other), ''),
          nullif(trim(p_root_cause), ''), v_person)
  returning id into v_id;
  perform quality_log('observation', v_id, 'opened', null, null, null, null,
                      jsonb_build_object('audit_id', p_audit, 'number', v_n, 'grade', p_grade), v_person);
  return v_id;
end $$;

-- p: any of text, grade, assigned_to, assigned_other, root_cause. Not on a closed audit.
create function audit_observation_update(p_id uuid, p jsonb, p_comment text default null)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_old    audit_observation%rowtype;
  v_new    audit_observation%rowtype;
  v_diff   record;
begin
  select * into v_old from audit_observation where id = p_id for update;
  if v_old.id is null then raise exception 'That observation does not exist.' using errcode = '22023'; end if;
  if (select status from audit where id = v_old.audit_id) = 'closed' then
    raise exception 'A closed audit is kept as it is.' using errcode = '22023';
  end if;
  p := coalesce(p, '{}'::jsonb);
  if p ? 'text' and length(trim(coalesce(p ->> 'text', ''))) = 0 then
    raise exception 'An observation keeps its words.' using errcode = '22023';
  end if;
  if p ? 'grade' and coalesce(p ->> 'grade', '') not in ('critical', 'major', 'minor') then
    raise exception 'Grade it critical, major or minor.' using errcode = '22023';
  end if;
  update audit_observation set
    text           = case when p ? 'text' then trim(p ->> 'text') else text end,
    grade          = case when p ? 'grade' then p ->> 'grade' else grade end,
    assigned_to    = case when p ? 'assigned_to' then quality_person(nullif(p ->> 'assigned_to', '')::uuid) else assigned_to end,
    assigned_other = case when p ? 'assigned_other' then nullif(trim(p ->> 'assigned_other'), '') else assigned_other end,
    root_cause     = case when p ? 'root_cause' then nullif(trim(p ->> 'root_cause'), '') else root_cause end,
    updated_at     = now()
  where id = p_id
  returning * into v_new;
  select * into v_diff from quality_changed(to_jsonb(v_old), to_jsonb(v_new));
  if v_diff.after = '{}'::jsonb then
    raise exception 'Nothing changed.' using errcode = '22023';
  end if;
  perform quality_log('observation', p_id, 'updated', null, null, p_comment, v_diff.before, v_diff.after, v_person);
end $$;

-- ───────────────────────────── 8. CAPA: the functions ─────────────────────────────
-- capa_open_as: the one code path that opens a CAPA; p_on is the day (its number's year). Granted to nobody.
create function capa_open_as(p_person uuid, p_on date, p_deviation uuid, p_observation uuid, p_corrective text,
                             p_preventive text, p_owner uuid default null, p_owner_other text default null,
                             p_due_on date default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_year   int := extract(year from p_on)::int;
  v_id     uuid;
  v_status text;
begin
  if num_nonnulls(p_deviation, p_observation) <> 1 then
    raise exception 'A CAPA comes from exactly one deviation or one audit observation.' using errcode = '22023';
  end if;
  -- The source row is locked, so a deviation or an audit is never closed while a CAPA is being added to it.
  if p_deviation is not null then
    select status into v_status from deviation where id = p_deviation for update;
    if v_status is null then
      raise exception 'That deviation does not exist.' using errcode = '22023';
    end if;
    if v_status = 'closed' then
      raise exception 'A closed deviation takes no new CAPA.' using errcode = '22023';
    end if;
  else
    select a.status into v_status
      from audit a join audit_observation o on o.audit_id = a.id
     where o.id = p_observation
       for update of a;
    if v_status is null then
      raise exception 'That observation does not exist.' using errcode = '22023';
    end if;
    if v_status = 'closed' then
      raise exception 'A closed audit takes no new CAPA.' using errcode = '22023';
    end if;
  end if;
  if length(trim(coalesce(p_corrective, ''))) = 0 and length(trim(coalesce(p_preventive, ''))) = 0 then
    raise exception 'Write the corrective action, the preventive action, or both.' using errcode = '22023';
  end if;
  if p_due_on is not null and p_due_on < p_on then
    raise exception 'A CAPA is due today or later.' using errcode = '22023';
  end if;
  insert into capa (year, serial, deviation_id, observation_id, corrective_action, preventive_action, owner_id,
                    owner_other, due_on, created_by)
  values (v_year, quality_next_serial('capa', v_year), p_deviation, p_observation, nullif(trim(p_corrective), ''),
          nullif(trim(p_preventive), ''), quality_person(p_owner), nullif(trim(p_owner_other), ''), p_due_on, p_person)
  returning id into v_id;
  perform quality_log('capa', v_id, 'opened', null, 'draft', null, null,
                      jsonb_build_object('deviation_id', p_deviation, 'observation_id', p_observation), p_person);
  return v_id;
end $$;

create function capa_open(p_deviation uuid, p_observation uuid, p_corrective text, p_preventive text,
                          p_owner uuid default null, p_owner_other text default null, p_due_on date default null)
returns uuid language plpgsql security definer set search_path = public as $$
begin
  return capa_open_as(quality_require_writer(), signal_cairo_today(), p_deviation, p_observation, p_corrective,
                      p_preventive, p_owner, p_owner_other, p_due_on);
end $$;

-- p: any of corrective_action, preventive_action, owner_id, owner_other, due_on, evidence. An effective CAPA is
-- not changed; a due day moved after approval needs a comment.
create function capa_update(p_id uuid, p_expected text, p jsonb, p_comment text default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_old    capa%rowtype;
  v_new    capa%rowtype;
  v_diff   record;
begin
  select * into v_old from capa where id = p_id for update;
  if v_old.id is null then raise exception 'That CAPA does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_old.status);
  if v_old.status = 'effective' then
    raise exception 'An effective CAPA is kept as it is.' using errcode = '22023';
  end if;
  p := coalesce(p, '{}'::jsonb);
  update capa set
    corrective_action = case when p ? 'corrective_action' then nullif(trim(p ->> 'corrective_action'), '') else corrective_action end,
    preventive_action = case when p ? 'preventive_action' then nullif(trim(p ->> 'preventive_action'), '') else preventive_action end,
    owner_id          = case when p ? 'owner_id' then quality_person(nullif(p ->> 'owner_id', '')::uuid) else owner_id end,
    owner_other       = case when p ? 'owner_other' then nullif(trim(p ->> 'owner_other'), '') else owner_other end,
    due_on            = case when p ? 'due_on' then nullif(p ->> 'due_on', '')::date else due_on end,
    evidence          = case when p ? 'evidence' then nullif(trim(p ->> 'evidence'), '') else evidence end,
    updated_at        = now()
  where id = p_id
  returning * into v_new;
  if v_new.due_on is distinct from v_old.due_on then
    if v_new.due_on is not null and v_new.due_on < signal_cairo_today() then
      raise exception 'A CAPA is due today or later.' using errcode = '22023';
    end if;
    if v_old.status <> 'draft' then
      perform quality_need_comment(p_comment);
    end if;
  end if;
  select * into v_diff from quality_changed(to_jsonb(v_old), to_jsonb(v_new));
  if v_diff.after = '{}'::jsonb then
    raise exception 'Nothing changed.' using errcode = '22023';
  end if;
  perform quality_log('capa', p_id, 'updated', v_old.status, v_old.status, p_comment, v_diff.before, v_diff.after, v_person);
  return v_new.status;
end $$;

-- p_to: approved (from draft: an owner and a due day), in_progress (from approved), done (from in_progress: the
-- evidence and the day, today when not given), effective (from done: verified by this person), not_effective
-- (from done: back to in_progress). Answers the new status.
create function capa_step(p_id uuid, p_to text, p_expected text, p_comment text default null,
                          p_done_on date default null, p_evidence text default null)
returns text language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_c      capa%rowtype;
  v_to     text := p_to;
  v_done   date;
  v_ev     text;
begin
  select * into v_c from capa where id = p_id for update;
  if v_c.id is null then raise exception 'That CAPA does not exist.' using errcode = '22023'; end if;
  perform quality_stale(p_expected, v_c.status);
  case p_to
    when 'approved' then
      if v_c.status <> 'draft' then raise exception 'Only a draft CAPA is approved.' using errcode = '22023'; end if;
      perform quality_need_comment(p_comment);
      if v_c.due_on is null or (v_c.owner_id is null and length(trim(coalesce(v_c.owner_other, ''))) = 0) then
        raise exception 'Give the CAPA an owner and a due day first.' using errcode = '22023';
      end if;
      update capa set status = 'approved', updated_at = now() where id = p_id;
    when 'in_progress' then
      if v_c.status <> 'approved' then
        raise exception 'Only an approved CAPA is started.' using errcode = '22023';
      end if;
      update capa set status = 'in_progress', updated_at = now() where id = p_id;
    when 'done' then
      if v_c.status <> 'in_progress' then
        raise exception 'Only a CAPA in progress is done.' using errcode = '22023';
      end if;
      v_ev := coalesce(nullif(trim(p_evidence), ''), v_c.evidence);
      if length(trim(coalesce(v_ev, ''))) = 0 then
        raise exception 'Give the evidence: what was done, a document reference or a link.' using errcode = '22023';
      end if;
      v_done := coalesce(quality_past_day(p_done_on, 'The day it was done'), signal_cairo_today());
      update capa set status = 'done', evidence = v_ev, done_on = v_done, updated_at = now() where id = p_id;
    when 'effective' then
      if v_c.status <> 'done' then
        raise exception 'Only a CAPA that is done is checked for effectiveness.' using errcode = '22023';
      end if;
      perform quality_need_comment(p_comment);
      update capa set status = 'effective', verified_by = v_person, verified_at = now(), updated_at = now() where id = p_id;
    when 'not_effective' then
      if v_c.status <> 'done' then
        raise exception 'Only a CAPA that is done is checked for effectiveness.' using errcode = '22023';
      end if;
      perform quality_need_comment(p_comment);
      v_to := 'in_progress';
      update capa set status = 'in_progress', done_on = null, updated_at = now() where id = p_id;
    else
      raise exception 'That is not a step of a CAPA.' using errcode = '22023';
  end case;
  perform quality_log('capa', p_id, p_to, v_c.status, v_to, p_comment,
                      case when p_to in ('done', 'not_effective') then
                        jsonb_build_object('evidence', v_c.evidence, 'done_on', v_c.done_on) end,
                      case when p_to = 'done' then jsonb_build_object('evidence', v_ev, 'done_on', v_done)
                           when p_to = 'not_effective' then jsonb_build_object('done_on', null) end,
                      v_person);
  return v_to;
end $$;

-- ───────────────────────────── 9. what the Quality tab reads ─────────────────────────────
-- One call: {today, deviations: […], audits: […], capas: […]}, every name already a name. Deviations and
-- audits newest first; the CAPA plan late ones first, then by due day. Each audit carries its deadlines
-- (the five from the report day; the plan for an internal audit; the answer to a request for information),
-- each {key, due, done_on, days_left, state}; each CAPA its due state.
create function quality_state() returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_today date := signal_cairo_today();
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the quality records.' using errcode = '42501';
  end if;
  return jsonb_build_object(
    'today', v_today,
    'deviations', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', d.id, 'ref', d.ref, 'year', d.year, 'serial', d.serial, 'title', d.title,
               'description', d.description, 'occurred_on', d.occurred_on, 'detected_on', d.detected_on,
               'level', d.level, 'patient_safety', d.patient_safety,
               'regulatory_compliance', d.regulatory_compliance, 'document_quality', d.document_quality,
               'inv_cause', d.inv_cause, 'inv_people_time', d.inv_people_time, 'inv_reoccur', d.inv_reoccur,
               'inv_similar', d.inv_similar, 'inv_other_impact', d.inv_other_impact, 'inv_training', d.inv_training,
               'root_cause', d.root_cause, 'qa_satisfactory', d.qa_satisfactory, 'status', d.status,
               'created_by', pc.full_name, 'created_at', d.created_at,
               'approved_by', pa.full_name, 'approved_at', d.approved_at,
               'closed_by', pz.full_name, 'closed_at', d.closed_at,
               'history', quality_history('deviation', array[d.id]))
             order by d.year desc, d.serial desc)
        from deviation d
        left join person pc on pc.id = d.created_by
        left join person pa on pa.id = d.approved_by
        left join person pz on pz.id = d.closed_by), '[]'::jsonb),
    'audits', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', a.id, 'kind', a.kind, 'title', a.title, 'auditor', a.auditor, 'lead_auditor', a.lead_auditor,
               'planned_on', a.planned_on, 'plan_sent_on', a.plan_sent_on, 'visit_from', a.visit_from,
               'visit_to', a.visit_to, 'rfi_received_on', a.rfi_received_on, 'rfi_answered_on', a.rfi_answered_on,
               'report_received_on', a.report_received_on, 'reviewed_on', a.reviewed_on, 'meeting_on', a.meeting_on,
               'capa_drafted_on', a.capa_drafted_on, 'capa_approved_on', a.capa_approved_on,
               'capa_submitted_on', a.capa_submitted_on, 'final_report_on', a.final_report_on,
               'closure_confirmed_on', a.closure_confirmed_on, 'status', a.status,
               'created_by', pc.full_name, 'created_at', a.created_at,
               'deadlines', quality_audit_deadlines(a, v_today),
               'observations', coalesce((
                 select jsonb_agg(jsonb_build_object(
                          'id', o.id, 'number', o.number, 'text', o.text, 'grade', o.grade,
                          'assigned_to', o.assigned_to, 'assigned_name', coalesce(po.full_name, o.assigned_other),
                          'assigned_other', o.assigned_other, 'root_cause', o.root_cause)
                        order by o.number)
                   from audit_observation o
                   left join person po on po.id = o.assigned_to
                  where o.audit_id = a.id), '[]'::jsonb),
               'history', quality_history('audit', array[a.id])
                          || quality_history('observation',
                                             array(select o.id from audit_observation o where o.audit_id = a.id)))
             order by coalesce(a.report_received_on, a.visit_from, a.planned_on, (a.created_at at time zone 'Africa/Cairo')::date) desc,
                      a.created_at desc)
        from audit a
        left join person pc on pc.id = a.created_by), '[]'::jsonb),
    'capas', coalesce((
      select jsonb_agg(x.j order by x.rank, x.due_on nulls last, x.year, x.serial)
        from (
          select c.year, c.serial, c.due_on,
                 case when c.status in ('done', 'effective') then 4
                      when c.due_on is null then 3
                      when c.due_on < v_today then 0
                      when c.due_on - v_today <= 2 then 1
                      else 2 end as rank,
                 jsonb_build_object(
                   'id', c.id, 'ref', c.ref, 'year', c.year, 'serial', c.serial,
                   'source', case when c.deviation_id is not null then 'deviation' else 'audit' end,
                   'deviation_id', c.deviation_id, 'deviation_ref', d.ref,
                   'observation_id', c.observation_id, 'observation_number', o.number,
                   'audit_id', a.id, 'audit_title', a.title, 'audit_kind', a.kind,
                   'corrective_action', c.corrective_action, 'preventive_action', c.preventive_action,
                   'owner_id', c.owner_id, 'owner_other', c.owner_other,
                   'owner_name', coalesce(po.full_name, c.owner_other),
                   'due_on', c.due_on, 'status', c.status, 'evidence', c.evidence, 'done_on', c.done_on,
                   'verified_by', pv.full_name, 'verified_at', c.verified_at,
                   'created_by', pc.full_name, 'created_at', c.created_at,
                   'due', quality_due(c.due_on, case when c.status in ('done', 'effective') then coalesce(c.done_on, v_today) end, v_today),
                   'history', quality_history('capa', array[c.id])) as j
            from capa c
            left join deviation d on d.id = c.deviation_id
            left join audit_observation o on o.id = c.observation_id
            left join audit a on a.id = o.audit_id
            left join person po on po.id = c.owner_id
            left join person pv on pv.id = c.verified_by
            left join person pc on pc.id = c.created_by) x), '[]'::jsonb));
end $$;

-- The history of records, oldest first: [{kind, step, from_status, to_status, comment, before, after, person, at}].
create function quality_history(p_kind text, p_ids uuid[]) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'kind', e.record_kind, 'record_id', e.record_id, 'step', e.step, 'from_status', e.from_status,
           'to_status', e.to_status, 'comment', e.comment, 'before', e.before, 'after', e.after,
           'person', p.full_name, 'at', e.at)
         order by e.at, e.id), '[]'::jsonb)
    from quality_event e
    left join person p on p.id = e.person_id
   where e.record_kind = p_kind and e.record_id = any(p_ids)
$$;

-- The deadlines of an audit on a Cairo day. From the day the report was received (PV-SOP-022): review +1,
-- meeting +2, draft CAPA +10, approval +12, submission +14. Before the report, an internal audit's plan is due
-- two weeks before the visit; a request for information is answered within 72 hours (+3 days).
create function quality_audit_deadlines(a audit, p_today date) returns jsonb
language sql stable as $$
  select coalesce(jsonb_agg(d.j || jsonb_build_object('key', d.key) order by d.n), '[]'::jsonb)
    from (
      select 0 as n, 'plan' as key,
             quality_due(coalesce(a.visit_from, a.planned_on) - 14, a.plan_sent_on, p_today) as j
       where a.kind = 'internal' and a.report_received_on is null and coalesce(a.visit_from, a.planned_on) is not null
      union all
      select 1, 'rfi', quality_due(a.rfi_received_on + 3, a.rfi_answered_on, p_today) where a.rfi_received_on is not null
      union all
      select 2, 'review', quality_due(a.report_received_on + 1, a.reviewed_on, p_today) where a.report_received_on is not null
      union all
      select 3, 'meeting', quality_due(a.report_received_on + 2, a.meeting_on, p_today) where a.report_received_on is not null
      union all
      select 4, 'draft', quality_due(a.report_received_on + 10, a.capa_drafted_on, p_today) where a.report_received_on is not null
      union all
      select 5, 'approval', quality_due(a.report_received_on + 12, a.capa_approved_on, p_today) where a.report_received_on is not null
      union all
      select 6, 'submission', quality_due(a.report_received_on + 14, a.capa_submitted_on, p_today) where a.report_received_on is not null
    ) d
$$;

-- ───────────────────────────── 10. grants ─────────────────────────────
-- The helpers and the _as paths: nobody. The functions the screen calls: signed-in people (each checks the role).
revoke all on function quality_require_writer(), quality_stale(text, text), quality_changed(jsonb, jsonb),
  quality_log(text, uuid, text, text, text, text, jsonb, jsonb, uuid), quality_need_comment(text),
  quality_past_day(date, text), quality_person(uuid), quality_due(date, date, date), quality_next_serial(text, int),
  quality_history(text, uuid[]), quality_audit_deadlines(audit, date),
  deviation_open_as(uuid, date, text, text, date, date, boolean, boolean, boolean),
  capa_open_as(uuid, date, uuid, uuid, text, text, uuid, text, date)
  from public, anon, authenticated;

revoke all on function
  deviation_open(text, text, date, date, boolean, boolean, boolean),
  deviation_update(uuid, text, jsonb, text),
  deviation_set_level(uuid, text, int, text),
  deviation_step(uuid, text, text, text, boolean),
  audit_open(text, text, text, text, date, date, date, date),
  audit_update(uuid, text, jsonb, text),
  audit_step(uuid, text, text, text, date),
  audit_add_observation(uuid, text, text, uuid, text, text),
  audit_observation_update(uuid, jsonb, text),
  capa_open(uuid, uuid, text, text, uuid, text, date),
  capa_update(uuid, text, jsonb, text),
  capa_step(uuid, text, text, text, date, text),
  quality_state()
  from public, anon;
grant execute on function
  deviation_open(text, text, date, date, boolean, boolean, boolean),
  deviation_update(uuid, text, jsonb, text),
  deviation_set_level(uuid, text, int, text),
  deviation_step(uuid, text, text, text, boolean),
  audit_open(text, text, text, text, date, date, date, date),
  audit_update(uuid, text, jsonb, text),
  audit_step(uuid, text, text, text, date),
  audit_add_observation(uuid, text, text, uuid, text, text),
  audit_observation_update(uuid, jsonb, text),
  capa_open(uuid, uuid, text, text, uuid, text, date),
  capa_update(uuid, text, jsonb, text),
  capa_step(uuid, text, text, text, date, text),
  quality_state()
  to authenticated;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function quality_require_writer(), quality_stale(text, text), quality_changed(jsonb, jsonb),
      quality_log(text, uuid, text, text, text, text, jsonb, jsonb, uuid), quality_need_comment(text),
      quality_past_day(date, text), quality_person(uuid), quality_due(date, date, date), quality_next_serial(text, int),
      quality_history(text, uuid[]), quality_audit_deadlines(audit, date),
      deviation_open_as(uuid, date, text, text, date, date, boolean, boolean, boolean),
      capa_open_as(uuid, date, uuid, uuid, text, text, uuid, text, date),
      deviation_open(text, text, date, date, boolean, boolean, boolean),
      deviation_update(uuid, text, jsonb, text), deviation_set_level(uuid, text, int, text),
      deviation_step(uuid, text, text, text, boolean),
      audit_open(text, text, text, text, date, date, date, date), audit_update(uuid, text, jsonb, text),
      audit_step(uuid, text, text, text, date), audit_add_observation(uuid, text, text, uuid, text, text),
      audit_observation_update(uuid, jsonb, text), capa_open(uuid, uuid, text, text, uuid, text, date),
      capa_update(uuid, text, jsonb, text), capa_step(uuid, text, text, text, date, text), quality_state()
      from service_role';
  end if;
end $$;
