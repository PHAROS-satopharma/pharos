-- PHAROS — the effectiveness check day of a CAPA (2026-11-11). PV-SOP-022 ("Follow up") asks that every completed
-- CAPA is checked to be still running as communicated. PHAROS now sets the day of that check itself: when a CAPA
-- is marked done, three months after the day it was done. A reviewer may move it (today or later, with the reason,
-- kept in the history). The judgement stays hers: "Verified effective" or "Not effective" is never taken by PHAROS.
--
-- 1. capa.effectiveness_due_on, set by the trigger capa_effectiveness_day: on done (from any other status, or a
--    row written done) the done day + 3 months; cleared when the CAPA goes back to work (not effective). Kept
--    once effective, for the record. CAPAs already done or effective get theirs from their done day.
-- 2. capa_update(…) takes effectiveness_due_on, only while the CAPA is done (0107 otherwise unchanged).
-- 3. quality_state(): each CAPA carries effectiveness_due_on and effectiveness {due, done_on, days_left, state}
--    (done_on: the Cairo day it was verified); a done CAPA is ranked in the plan by its check day, not at the end.
-- The morning reminder lists the checks due within two days or late (collectors/reminders.py); the inspection
-- pack's CAPA plan gives the day (collectors/report_pack.py).

alter table capa add column effectiveness_due_on date;
comment on column capa.effectiveness_due_on is
  'The day to check that a done CAPA worked (PV-SOP-022 follow-up): done day + 3 months, set by PHAROS; a reviewer may move it (0110).';
alter table capa add constraint capa_effectiveness_after_done
  check (effectiveness_due_on is null or done_on is null or effectiveness_due_on >= done_on);

-- The months from the day a CAPA is done to its effectiveness check.
create function capa_effectiveness_months() returns int language sql immutable as $$ select 3 $$;

create function capa_effectiveness_day() returns trigger language plpgsql set search_path = public as $$
begin
  if new.status = 'done' and (tg_op = 'INSERT' or old.status <> 'done' or new.done_on is distinct from old.done_on)
     and new.done_on is not null
     and (tg_op = 'INSERT' and new.effectiveness_due_on is null or tg_op = 'UPDATE'
          and new.effectiveness_due_on is not distinct from old.effectiveness_due_on) then
    new.effectiveness_due_on := (new.done_on + make_interval(months => capa_effectiveness_months()))::date;
  elsif new.status not in ('done', 'effective') then
    new.effectiveness_due_on := null;
  end if;
  return new;
end $$;
revoke all on function capa_effectiveness_day() from public, anon, authenticated;

update capa set effectiveness_due_on = (done_on + make_interval(months => capa_effectiveness_months()))::date
 where status in ('done', 'effective') and done_on is not null and effectiveness_due_on is null;

create trigger capa_effectiveness_day before insert or update on capa
  for each row execute function capa_effectiveness_day();

create or replace function capa_update(p_id uuid, p_expected text, p jsonb, p_comment text default null)
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
  -- 0110: the effectiveness check day, checked before the update (the trigger clears it on a CAPA not done).
  if p ? 'effectiveness_due_on'
     and nullif(p ->> 'effectiveness_due_on', '')::date is distinct from v_old.effectiveness_due_on then
    if v_old.status <> 'done' then
      raise exception 'The effectiveness check day is set once the CAPA is done.' using errcode = '22023';
    end if;
    if nullif(p ->> 'effectiveness_due_on', '') is null then
      raise exception 'A CAPA that is done keeps a day to check that it worked.' using errcode = '22023';
    end if;
    if (p ->> 'effectiveness_due_on')::date < signal_cairo_today() then
      raise exception 'The effectiveness check is due today or later.' using errcode = '22023';
    end if;
    perform quality_need_comment(p_comment);
  end if;
  update capa set
    corrective_action = case when p ? 'corrective_action' then nullif(trim(p ->> 'corrective_action'), '') else corrective_action end,
    preventive_action = case when p ? 'preventive_action' then nullif(trim(p ->> 'preventive_action'), '') else preventive_action end,
    owner_id          = case when p ? 'owner_id' then quality_person(nullif(p ->> 'owner_id', '')::uuid) else owner_id end,
    owner_other       = case when p ? 'owner_other' then nullif(trim(p ->> 'owner_other'), '') else owner_other end,
    due_on            = case when p ? 'due_on' then nullif(p ->> 'due_on', '')::date else due_on end,
    evidence          = case when p ? 'evidence' then nullif(trim(p ->> 'evidence'), '') else evidence end,
    effectiveness_due_on = case when p ? 'effectiveness_due_on' then nullif(p ->> 'effectiveness_due_on', '')::date
                                else effectiveness_due_on end,
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

create or replace function quality_state() returns jsonb
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
          select c.year, c.serial,
                 case when c.status = 'done' then c.effectiveness_due_on else c.due_on end as due_on,
                 case when c.status = 'effective' then 4
                      when c.status = 'done' then
                        case when c.effectiveness_due_on is null then 3
                             when c.effectiveness_due_on < v_today then 0
                             when c.effectiveness_due_on - v_today <= 2 then 1
                             else 2 end
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
                   'effectiveness_due_on', c.effectiveness_due_on,
                   'effectiveness', case when c.status in ('done', 'effective') then
                                      quality_due(c.effectiveness_due_on,
                                                  case when c.status = 'effective'
                                                       then (c.verified_at at time zone 'Africa/Cairo')::date end,
                                                  v_today) end,
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
