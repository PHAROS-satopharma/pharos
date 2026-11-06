-- PHAROS — reopening a signal that was never validated sends it back to validation (2026-11-06, finding 8 of
-- the review of #92).
--
-- signal_take_step_as() (0042) reopened every closed signal into assessment, with priority 'medium' when it had
-- none. A signal closed as not validated (by hand, or by Doesn't concern us, 0042) had never been validated:
-- reopening it skipped validation and gave it a priority nobody chose, and its assessment clock ran on that
-- priority. Now a closed signal that was never validated (outcome not_validated, or no priority) reopens into
-- validation, on a new validation clock, with no priority until it is validated; a signal closed after its
-- assessment reopens into assessment with its own priority, as before. Signature, owner and grants unchanged;
-- signal_take_step() calls it as before.

create or replace function signal_take_step_as(
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
      if v_sig.outcome = 'not_validated' or v_sig.priority is null then
        -- never validated: it is validated now, with a priority chosen then, on a new validation clock
        v_to := 'validation';
        v_due := signal_cairo_today() + signal_due_days('validation');
        update signal set stage = v_to, outcome = null, closed_at = null, action_due = null,
                          validation_due = v_due, updated_at = now()
         where id = p_signal;
      else
        v_to := 'assessment';
        v_due := signal_cairo_today() + signal_due_days('assessment', v_sig.priority);
        update signal set stage = v_to, outcome = null, closed_at = null, action_due = null,
                          assessment_due = v_due, updated_at = now()
         where id = p_signal;
      end if;
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
