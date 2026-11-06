-- PHAROS — signal steps inside the finding (2026-11-06, the QPPV's second need after her review).
--
-- A finding that concerns us is, in GVP terms, a signal to validate, assess and act on. The signal tracker (0025)
-- already keeps those steps as evidence; nobody opened its signals since the Signals screen went. This
-- migration opens the signal from the decision itself and shows it inside the finding, so Dr Sama takes the
-- steps where she took the decision: on the Ingredients screen.
--
-- 1. open_signal_as(issue, title, ingredient, person) is the one code path that opens a signal: the checks and
--    the rows of open_signal() (signal, signal_issue, signal_event 'opened'), for a named person. Granted to
--    nobody: open_signal() calls it for the signed-in reviewer or administrator, the trigger below for the
--    person who decided. signal_take_step_as(person, …) is the same for the steps; signal_take_step() keeps
--    its signature, grants and guards (a reader is refused with 42501, a stale stage with PH409 STALE_SIGNAL).
-- 2. The trigger review_event_zz_open_signal (after insert on review_event; named to sort after
--    review_event_apply, which sets the notice's status first): Concerns us on a notice with no signal opens one
--    — title = the notice's title, ingredient = the notice's single ingredient or none — while app_setting
--    signal_auto_open is true. Doesn't concern us closes a signal still in validation with no real step taken
--    (only opened, a notice linked, a note) as not validated, with the comment "Decision changed: <her
--    reason>"; a signal already validated is left as it is. A failure to open or close the signal never refuses
--    the decision: it is logged as a warning and the decision stands.
-- 3. finding_state(p_issues) (0041, same signature and grants) adds per notice its signal, or null:
--    {id, ref, title, stage, priority, outcome, next_step, next_due, overdue, owner, opened_at, opened_by,
--     steps: [{step, from_stage, to_stage, priority, outcome, person, at, comment}]}, read from signal_issue,
--    v_signal_table and signal_event. The screen and the weekly report already call finding_state().
-- Nothing is dropped; every signal written before behaves as before.

-- ───────────────────────────── setting ─────────────────────────────
insert into app_setting (key, value) values ('signal_auto_open', 'true') on conflict (key) do nothing;

-- ───────────────────────────── open a signal, as a named person ─────────────────────────────
create function open_signal_as(p_issue uuid, p_title text, p_ingredient uuid, p_person uuid, p_comment text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_status issue_status;
  v_id     uuid;
  v_due    date := signal_cairo_today() + signal_due_days('validation');
begin
  if p_person is null or not exists (select 1 from person where id = p_person) then
    raise exception 'A signal is opened by a person.' using errcode = '22023';
  end if;
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
          trim(p_title), p_ingredient, p_person, v_due)
  returning id into v_id;
  insert into signal_issue (signal_id, issue_id, linked_by) values (v_id, p_issue, p_person);
  insert into signal_event (signal_id, step, from_stage, to_stage, due, issue_id, comment, person_id)
  values (v_id, 'opened', null, 'validation', v_due, p_issue, nullif(trim(p_comment), ''), p_person);
  return v_id;
end $$;
revoke all on function open_signal_as(uuid, text, uuid, uuid, text) from public, anon, authenticated;

-- open_signal() keeps its signature, owner and grants; the signed-in reviewer or administrator is the person.
create or replace function open_signal(p_issue uuid, p_title text, p_ingredient uuid, p_comment text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := signal_require_reviewer();
begin
  return open_signal_as(p_issue, p_title, p_ingredient, v_person, p_comment);
end $$;

-- ───────────────────────────── take a step, as a named person ─────────────────────────────
-- The body of signal_take_step() (0025) with the person as an argument; the arguments each step needs are
-- documented there.
create function signal_take_step_as(
  p_person     uuid,
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
  v_person   uuid := p_person;
  v_sig      signal%rowtype;
  v_comment  text := nullif(trim(p_comment), '');
  v_to       signal_stage;
  v_due      date;
begin
  if v_person is null or not exists (select 1 from person where id = v_person) then
    raise exception 'A step is taken by a person.' using errcode = '22023';
  end if;
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
revoke all on function signal_take_step_as(uuid, uuid, signal_step, signal_stage, text, signal_priority, signal_outcome, uuid, date)
  from public, anon, authenticated;

-- signal_take_step() keeps its signature, owner and grants; the signed-in reviewer or administrator is the person.
create or replace function signal_take_step(
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
  v_person uuid := signal_require_reviewer();
begin
  return signal_take_step_as(v_person, p_signal, p_step, p_from_stage, p_comment, p_priority, p_outcome, p_owner, p_due);
end $$;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function open_signal_as(uuid, text, uuid, uuid, text) from service_role';
    execute 'revoke all on function signal_take_step_as(uuid, uuid, signal_step, signal_stage, text, signal_priority, '
            'signal_outcome, uuid, date) from service_role';
  end if;
end $$;

-- ───────────────────────────── the decision opens (or closes) the signal ─────────────────────────────
create function review_event_open_signal() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_auto       boolean := coalesce((select (value #>> '{}')::boolean from app_setting where key = 'signal_auto_open'), true);
  v_title      text;
  v_n          int;
  v_ingredient uuid;
  v_sig        signal%rowtype;
begin
  if new.to_status = 'relevant' then
    if not v_auto or exists (select 1 from signal_issue where issue_id = new.issue_id) then
      return new;
    end if;
    select i.title into v_title from issue i where i.id = new.issue_id;
    -- the notice's single ingredient; a notice of several ingredients opens a signal with none
    select count(*), min(ii.ingredient_id) into v_n, v_ingredient from issue_ingredient ii where ii.issue_id = new.issue_id;
    if v_n <> 1 then
      v_ingredient := null;
    end if;
    begin
      perform open_signal_as(new.issue_id, v_title, v_ingredient, new.person_id,
                             'Opened when the notice was marked Concerns us'
                             || coalesce(': ' || nullif(trim(new.comment), ''), ''));
    exception when others then
      raise warning 'PHAROS: the signal for notice % was not opened (% %)', new.issue_id, sqlstate, sqlerrm;
    end;
  elsif new.to_status = 'not_relevant' then
    select s.* into v_sig from signal s join signal_issue si on si.signal_id = s.id where si.issue_id = new.issue_id;
    if v_sig.id is null or v_sig.stage <> 'validation' then
      return new;
    end if;
    -- a step beyond opened, a notice linked or a note is real work: the signal is left as it is
    if exists (select 1 from signal_event e where e.signal_id = v_sig.id and e.step not in ('opened', 'notice_linked', 'note')) then
      return new;
    end if;
    begin
      perform signal_take_step_as(new.person_id, v_sig.id, 'not_validated', 'validation',
                                  'Decision changed: ' || coalesce(nullif(trim(new.comment), ''), 'no reason given'));
    exception when others then
      raise warning 'PHAROS: the signal % for notice % was not closed (% %)', v_sig.ref, new.issue_id, sqlstate, sqlerrm;
    end;
  end if;
  return new;
end $$;
create trigger review_event_zz_open_signal after insert on review_event
  for each row execute function review_event_open_signal();

-- ───────────────────────────── the finding carries its signal ─────────────────────────────
create or replace function finding_state(p_issues uuid[]) returns jsonb
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
                          else jsonb_build_object('id', c.sent_id, 'on', c.sent_on, 'reference', c.sent_reference,
                                                  'person', c.sent_by, 'note', c.sent_note) end,
             -- the signal the notice belongs to (0042), or null
             'signal', (
               select jsonb_build_object(
                        'id', v.id, 'ref', v.ref, 'title', v.title, 'stage', v.stage, 'priority', v.priority,
                        'outcome', v.outcome,
                        'next_step', case v.stage when 'validation' then 'validated'
                                                  when 'assessment' then 'assessed'
                                                  when 'action'     then 'action_done' end,
                        'next_due', v.next_due, 'overdue', v.overdue, 'owner', v.owner,
                        'opened_at', v.opened_at, 'opened_by', po.full_name,
                        'steps', coalesce((
                          select jsonb_agg(jsonb_build_object(
                                   'step', e.step, 'from_stage', e.from_stage, 'to_stage', e.to_stage,
                                   'priority', e.priority, 'outcome', e.outcome, 'person', pe.full_name,
                                   'at', e.created_at, 'comment', e.comment)
                                 order by e.created_at, e.id)
                            from signal_event e
                            left join person pe on pe.id = e.person_id
                           where e.signal_id = v.id), '[]'::jsonb))
                 from signal_issue si
                 join v_signal_table v on v.id = si.signal_id
                 join signal s on s.id = v.id
                 left join person po on po.id = s.opened_by
                where si.issue_id = c.issue_id)))
      from eda_clock(p_issues) c), '{}'::jsonb);
end $$;
revoke all on function finding_state(uuid[]) from public, anon;
grant execute on function finding_state(uuid[]) to authenticated;
