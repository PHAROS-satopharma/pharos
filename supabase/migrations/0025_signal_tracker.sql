-- PHAROS — the signal tracker (2026-11-05).
--
-- A notice marked Relevant can open a signal, and the signal is followed through the EU signal-management
-- steps (GVP Module IX): validation, assessment, action, closed. Every step is one row in signal_event,
-- which is append-only like review_event: it is the evidence an inspector reads. The signal row itself
-- only carries the current state, and is written by the step functions below, never by the app directly.
--
-- Due dates are Cairo calendar days. The number of days comes from app_setting 'signal_due_days', which
-- the QPPV sets to match the SOP; until then the defaults are 30 days to validate, and 30, 60 or 90 days
-- to assess a high, medium or low priority signal. An action's due date is chosen when it is planned.
--
-- Two people stepping the same signal at once: the step names the stage it was taken from, and a step
-- from a stage that is no longer current is refused (SQLSTATE PH409, message prefix STALE_SIGNAL), as
-- review decisions are (0008).

create type signal_stage    as enum ('validation','assessment','action','closed');
create type signal_priority as enum ('high','medium','low');
create type signal_outcome  as enum ('not_validated','refuted','monitor','no_action',
                                     'label_update','rmp_update','dhpc','psur_input');
create type signal_step     as enum ('opened','notice_linked','validated','not_validated','prioritised',
                                     'assigned','assessed','action_done','reopened','note');

create sequence signal_number;

create table signal (
  id              uuid primary key default gen_random_uuid(),
  ref             text unique not null,              -- SIG-2026-001, the name people use
  title           text not null check (length(trim(title)) > 0),
  ingredient_id   uuid references ingredient(id),
  stage           signal_stage not null default 'validation',
  priority        signal_priority,
  outcome         signal_outcome,
  owner_id        uuid references person(id),
  opened_by       uuid not null references person(id),
  opened_at       timestamptz not null default now(),
  validation_due  date not null,
  assessment_due  date,
  action_due      date,
  closed_at       timestamptz,
  updated_at      timestamptz not null default now()
);
create index on signal (stage);

-- The notices behind a signal. A notice belongs to one signal at most.
create table signal_issue (
  signal_id  uuid not null references signal(id) on delete cascade,
  issue_id   uuid not null unique references issue(id) on delete cascade,
  linked_by  uuid not null references person(id),
  linked_at  timestamptz not null default now(),
  primary key (signal_id, issue_id)
);

-- Append-only: the signal's history is evidence.
create table signal_event (
  id          uuid primary key default gen_random_uuid(),
  signal_id   uuid not null references signal(id) on delete cascade,
  step        signal_step not null,
  from_stage  signal_stage,
  to_stage    signal_stage not null,
  priority    signal_priority,
  outcome     signal_outcome,
  owner_id    uuid references person(id),
  due         date,
  issue_id    uuid references issue(id) on delete set null,
  comment     text,
  person_id   uuid not null references person(id),
  created_at  timestamptz not null default now()
);
create index on signal_event (signal_id, created_at);

create function signal_event_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'signal_event is append-only';
end $$;
create trigger signal_event_no_update before update or delete on signal_event
  for each row execute function signal_event_immutable();

create trigger audit_signal after insert or update or delete on signal
  for each row execute function audit_row();
create trigger audit_signal_issue after insert or update or delete on signal_issue
  for each row execute function audit_row();

insert into app_setting (key, value) values
  ('signal_due_days', '{"validation": 30, "assessment": {"high": 30, "medium": 60, "low": 90}}')
on conflict (key) do nothing;

alter table signal       enable row level security;
alter table signal_issue enable row level security;
alter table signal_event enable row level security;
create policy signal_read       on signal       for select to authenticated using (my_role() is not null);
create policy signal_issue_read on signal_issue for select to authenticated using (my_role() is not null);
create policy signal_event_read on signal_event for select to authenticated using (my_role() is not null);
-- No write policies: only the functions below write, as the signed-in person, at the database's time.

-- ───────────────────────────── helpers ─────────────────────────────
create function signal_cairo_today() returns date language sql stable as $$
  select (now() at time zone 'Africa/Cairo')::date
$$;

create function signal_due_days(p_what text, p_priority signal_priority default null) returns int
language sql stable security definer set search_path = public as $$
  select coalesce(
    case when p_what = 'validation' then (select (value ->> 'validation')::int from app_setting where key = 'signal_due_days')
         else (select (value -> 'assessment' ->> p_priority::text)::int from app_setting where key = 'signal_due_days')
    end,
    case when p_what = 'validation' then 30
         when p_priority = 'high' then 30 when p_priority = 'low' then 90 else 60 end)
$$;

create function signal_require_reviewer() returns uuid language plpgsql stable security definer
set search_path = public as $$
declare v_person uuid := my_person_id();
begin
  if v_person is null or my_role() not in ('admin','reviewer') then
    raise exception 'Only a reviewer or an administrator can change a signal.' using errcode = '42501';
  end if;
  return v_person;
end $$;

-- ───────────────────────────── open a signal from a notice ─────────────────────────────
create function open_signal(p_issue uuid, p_title text, p_ingredient uuid, p_comment text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := signal_require_reviewer();
  v_status issue_status;
  v_id     uuid;
  v_due    date := signal_cairo_today() + signal_due_days('validation');
begin
  select status into v_status from issue where id = p_issue for update;
  if v_status is null then
    raise exception 'That notice does not exist.' using errcode = '22023';
  end if;
  if v_status <> 'relevant' then
    raise exception 'Only a notice marked Relevant can open a signal.' using errcode = '22023';
  end if;
  if exists (select 1 from signal_issue where issue_id = p_issue) then
    raise exception 'This notice already belongs to a signal.' using errcode = '23505';
  end if;
  if p_ingredient is not null and not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = '22023';
  end if;
  if length(coalesce(trim(p_title), '')) = 0 then
    raise exception 'A signal needs a title.' using errcode = '22023';
  end if;

  insert into signal (ref, title, ingredient_id, opened_by, validation_due)
  values ('SIG-' || to_char(signal_cairo_today(), 'YYYY') || '-' || lpad(nextval('signal_number')::text, 3, '0'),
          trim(p_title), p_ingredient, v_person, v_due)
  returning id into v_id;
  insert into signal_issue (signal_id, issue_id, linked_by) values (v_id, p_issue, v_person);
  insert into signal_event (signal_id, step, from_stage, to_stage, due, issue_id, comment, person_id)
  values (v_id, 'opened', null, 'validation', v_due, p_issue, nullif(trim(p_comment), ''), v_person);
  return v_id;
end $$;

-- ───────────────────────────── add a notice to an open signal ─────────────────────────────
create function link_signal_issue(p_signal uuid, p_issue uuid, p_comment text default null)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := signal_require_reviewer();
  v_stage  signal_stage;
  v_status issue_status;
begin
  select stage into v_stage from signal where id = p_signal for update;
  if v_stage is null then raise exception 'That signal does not exist.' using errcode = '22023'; end if;
  if v_stage = 'closed' then
    raise exception 'That signal is closed. Reopen it first.' using errcode = '22023';
  end if;
  select status into v_status from issue where id = p_issue for update;
  if v_status is distinct from 'relevant' then
    raise exception 'Only a notice marked Relevant can join a signal.' using errcode = '22023';
  end if;
  if exists (select 1 from signal_issue where issue_id = p_issue) then
    raise exception 'This notice already belongs to a signal.' using errcode = '23505';
  end if;
  insert into signal_issue (signal_id, issue_id, linked_by) values (p_signal, p_issue, v_person);
  insert into signal_event (signal_id, step, from_stage, to_stage, issue_id, comment, person_id)
  values (p_signal, 'notice_linked', v_stage, v_stage, p_issue, nullif(trim(p_comment), ''), v_person);
  update signal set updated_at = now() where id = p_signal;
end $$;

-- ───────────────────────────── take a step ─────────────────────────────
-- p_from_stage is the stage the person saw. Which arguments a step needs:
--   validated      priority, comment (why it is a signal)          validation → assessment
--   not_validated  comment (why not)                               validation → closed
--   prioritised    priority, comment                               stage unchanged
--   assigned       owner                                           stage unchanged
--   assessed       outcome, comment (the conclusion); an outcome that needs action also needs due
--                                                                  assessment → action, or → closed
--   action_done    comment (what was done, with its reference)     action → closed
--   reopened       comment (why)                                   closed → assessment
--   note           comment                                         stage unchanged
create function signal_take_step(
  p_signal     uuid,
  p_step       signal_step,
  p_from_stage signal_stage,
  p_comment    text default null,
  p_priority   signal_priority default null,
  p_outcome    signal_outcome default null,
  p_owner      uuid default null,
  p_due        date default null
) returns signal_stage language plpgsql security definer set search_path = public as $$
declare
  v_person   uuid := signal_require_reviewer();
  v_sig      signal%rowtype;
  v_comment  text := nullif(trim(p_comment), '');
  v_to       signal_stage;
  v_due      date;
begin
  select * into v_sig from signal where id = p_signal for update;
  if v_sig.id is null then raise exception 'That signal does not exist.' using errcode = '22023'; end if;
  if p_from_stage is distinct from v_sig.stage then
    raise exception 'STALE_SIGNAL: someone else moved this signal a moment ago; it is now at %.', v_sig.stage
      using errcode = 'PH409', hint = 'Reload the signal and look again.';
  end if;
  if p_step in ('opened','notice_linked') then
    raise exception 'Use open_signal or link_signal_issue for that step.' using errcode = '22023';
  end if;
  if v_comment is null and p_step <> 'assigned' then
    raise exception 'This step needs a comment for the record.' using errcode = '22023';
  end if;

  v_to := v_sig.stage;
  case p_step
    when 'validated' then
      if v_sig.stage <> 'validation' then raise exception 'Only a signal in validation can be validated.' using errcode = '22023'; end if;
      if p_priority is null then raise exception 'A validated signal needs a priority.' using errcode = '22023'; end if;
      v_to := 'assessment';
      v_due := signal_cairo_today() + signal_due_days('assessment', p_priority);
      update signal set stage = v_to, priority = p_priority, assessment_due = v_due, updated_at = now() where id = p_signal;
    when 'not_validated' then
      if v_sig.stage <> 'validation' then raise exception 'Only a signal in validation can be closed as not validated.' using errcode = '22023'; end if;
      v_to := 'closed';
      update signal set stage = v_to, outcome = 'not_validated', closed_at = now(), updated_at = now() where id = p_signal;
    when 'prioritised' then
      if v_sig.stage = 'closed' then raise exception 'A closed signal keeps its priority.' using errcode = '22023'; end if;
      if p_priority is null or p_priority = v_sig.priority then
        raise exception 'Choose a different priority.' using errcode = '22023';
      end if;
      -- The assessment clock follows the new priority from the day the signal was validated.
      if v_sig.stage = 'assessment' then
        v_due := (select (e.created_at at time zone 'Africa/Cairo')::date from signal_event e
                   where e.signal_id = p_signal and e.step in ('validated','reopened')
                   order by e.created_at desc limit 1) + signal_due_days('assessment', p_priority);
      end if;
      update signal set priority = p_priority, assessment_due = coalesce(v_due, assessment_due), updated_at = now()
       where id = p_signal;
    when 'assigned' then
      if p_owner is null or not exists (select 1 from person where id = p_owner and active and role in ('admin','reviewer')) then
        raise exception 'The owner must be an active reviewer or administrator.' using errcode = '22023';
      end if;
      if p_owner = v_sig.owner_id then raise exception 'That person already owns this signal.' using errcode = '22023'; end if;
      update signal set owner_id = p_owner, updated_at = now() where id = p_signal;
    when 'assessed' then
      if v_sig.stage <> 'assessment' then raise exception 'Only a signal in assessment can be assessed.' using errcode = '22023'; end if;
      if p_outcome is null or p_outcome = 'not_validated' then
        raise exception 'Choose the outcome of the assessment.' using errcode = '22023';
      end if;
      if p_outcome in ('label_update','rmp_update','dhpc','psur_input') then
        if p_due is null or p_due < signal_cairo_today() then
          raise exception 'An action needs a due date from today on.' using errcode = '22023';
        end if;
        v_to := 'action';
        v_due := p_due;
        update signal set stage = v_to, outcome = p_outcome, action_due = v_due, updated_at = now() where id = p_signal;
      else
        v_to := 'closed';
        update signal set stage = v_to, outcome = p_outcome, closed_at = now(), updated_at = now() where id = p_signal;
      end if;
    when 'action_done' then
      if v_sig.stage <> 'action' then raise exception 'Only a signal with an open action can be closed this way.' using errcode = '22023'; end if;
      v_to := 'closed';
      update signal set stage = v_to, closed_at = now(), updated_at = now() where id = p_signal;
    when 'reopened' then
      if v_sig.stage <> 'closed' then raise exception 'Only a closed signal can be reopened.' using errcode = '22023'; end if;
      v_to := 'assessment';
      v_due := signal_cairo_today() + signal_due_days('assessment', coalesce(v_sig.priority, 'medium'));
      update signal set stage = v_to, outcome = null, closed_at = null, action_due = null,
                        priority = coalesce(priority, 'medium'), assessment_due = v_due, updated_at = now()
       where id = p_signal;
    when 'note' then
      update signal set updated_at = now() where id = p_signal;
  end case;

  insert into signal_event (signal_id, step, from_stage, to_stage, priority, outcome, owner_id, due, comment, person_id)
  values (p_signal, p_step, v_sig.stage, v_to,
          case when p_step in ('validated','prioritised') then p_priority end,
          case when p_step = 'assessed' then p_outcome when p_step = 'not_validated' then 'not_validated'::signal_outcome end,
          case when p_step = 'assigned' then p_owner end,
          v_due, v_comment, v_person);
  return v_to;
end $$;

-- ───────────────────────────── the list ─────────────────────────────
create view v_signal_table with (security_invoker = true) as
select
  s.id, s.ref, s.title, s.stage, s.priority, s.outcome,
  s.ingredient_id,
  ing.inn_en                                          as ingredient,
  s.owner_id,
  own.full_name                                       as owner,
  s.opened_at, s.closed_at, s.updated_at,
  s.validation_due, s.assessment_due, s.action_due,
  case s.stage when 'validation' then s.validation_due
               when 'assessment' then s.assessment_due
               when 'action'     then s.action_due end as next_due,
  (s.stage <> 'closed' and
   case s.stage when 'validation' then s.validation_due
                when 'assessment' then s.assessment_due
                when 'action'     then s.action_due end < signal_cairo_today()) as overdue,
  (select count(*) from signal_issue si where si.signal_id = s.id) as notices
from signal s
left join ingredient ing on ing.id = s.ingredient_id
left join person_directory own on own.id = s.owner_id;

revoke all on function open_signal(uuid, text, uuid, text), link_signal_issue(uuid, uuid, text),
  signal_take_step(uuid, signal_step, signal_stage, text, signal_priority, signal_outcome, uuid, date),
  signal_require_reviewer(), signal_due_days(text, signal_priority)
  from public, anon;
grant execute on function open_signal(uuid, text, uuid, text), link_signal_issue(uuid, uuid, text),
  signal_take_step(uuid, signal_step, signal_stage, text, signal_priority, signal_outcome, uuid, date),
  signal_require_reviewer(), signal_due_days(text, signal_priority)
  to authenticated;
revoke insert, update, delete on signal, signal_issue, signal_event from anon, authenticated;
revoke all on sequence signal_number from anon, authenticated;
