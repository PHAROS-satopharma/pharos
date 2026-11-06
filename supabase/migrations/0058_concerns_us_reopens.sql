-- PHAROS — Concerns us again reopens the signal that Doesn't concern us closed (2026-11-06, finding 9 of the
-- review of #120).
--
-- review_event_open_signal() (0042) opened a signal on Concerns us only when the notice had none, and closed it
-- as not validated on Doesn't concern us while nobody had worked on it. Changing the decision back to Concerns
-- us then found the notice's closed signal and did nothing: the notice concerned us again, with no open signal
-- and no step to take. Now Concerns us reopens a signal that the decision itself closed and nobody worked on
-- since (into validation, 0057), with the comment "Decision changed back: <her reason>". The decision's own
-- closing and reopening do not count as work, so the decision can change again either way. A signal closed by a
-- person (Not a signal, an assessment) or worked on is left as it is. Trigger unchanged; never refuses the
-- decision.

create or replace function review_event_open_signal() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  v_title      text;
  v_ingredient uuid;
  v_sig        signal%rowtype;
  v_real_work  boolean;
begin
  -- Everything here is inside one exception block: opening or closing the signal never refuses the decision.
  begin
    select s.* into v_sig from signal s join signal_issue si on si.signal_id = s.id where si.issue_id = new.issue_id;
    -- Real work is any step but opening, linking a notice, a note, and the decision's own closing and reopening
    -- (comment 'Decision changed: …' / 'Decision changed back: …').
    v_real_work := v_sig.id is not null and exists (
      select 1 from signal_event e
       where e.signal_id = v_sig.id
         and e.step not in ('opened', 'notice_linked', 'note')
         and not (e.step in ('not_validated', 'reopened') and coalesce(e.comment, '') like 'Decision changed%'));
    if new.to_status = 'relevant' then
      if v_sig.id is not null then
        -- Doesn't concern us closed it and nobody worked on it since: Concerns us again reopens it (into
        -- validation, 0057). A signal closed by a person, or worked on, is left as it is.
        if v_sig.stage = 'closed' and v_sig.outcome = 'not_validated' and not v_real_work then
          perform signal_take_step_as(new.person_id, v_sig.id, 'reopened', 'closed',
                                      'Decision changed back: ' || coalesce(nullif(trim(new.comment), ''), 'no reason given'));
        end if;
        return new;
      end if;
      if not coalesce((select (value #>> '{}')::boolean from app_setting where key = 'signal_auto_open'), true) then
        return new;
      end if;
      select i.title into v_title from issue i where i.id = new.issue_id;
      -- the notice's single ingredient; a notice of several ingredients opens a signal with none
      -- (uuid has no min(): the first of the array when there is exactly one)
      select case when count(*) = 1 then (array_agg(ii.ingredient_id))[1] end into v_ingredient
        from issue_ingredient ii where ii.issue_id = new.issue_id;
      perform open_signal_as(new.issue_id, v_title, v_ingredient, new.person_id,
                             'Opened when the notice was marked Concerns us'
                             || coalesce(': ' || nullif(trim(new.comment), ''), ''));
    elsif new.to_status = 'not_relevant' then
      if v_sig.id is null or v_sig.stage <> 'validation' or v_real_work then
        return new;
      end if;
      perform signal_take_step_as(new.person_id, v_sig.id, 'not_validated', 'validation',
                                  'Decision changed: ' || coalesce(nullif(trim(new.comment), ''), 'no reason given'));
    end if;
  exception when others then
    raise warning 'PHAROS: the signal of notice % was not opened or closed (% %)', new.issue_id, sqlstate, sqlerrm;
  end;
  return new;
end $$;
