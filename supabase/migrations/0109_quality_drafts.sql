-- PHAROS — a drafted root cause and CAPA (2026-11-11). On a deviation (PV-SOP-021) or an audit observation
-- (PV-SOP-022), a reviewer or an administrator asks for a draft: the root cause, the corrective action, the
-- preventive action, and what the draft could not know and must be checked. The reader (Claude, the one PHAROS
-- already uses for case reports, signed in by federation from GitHub) writes it from what is recorded on the
-- record and nothing else. The draft is only text on the screen: it changes no record. She uses it, changed or
-- not, through the usual forms (the investigation, the observation, a new CAPA), each kept in the history.
--
-- 1. quality_draft: one row per draft asked for; at most one waiting (queued or drafting) per record.
-- 2. quality_draft_ask(kind, id): a reviewer or an administrator; the record exists and is not closed; returns the
--    waiting draft when there is one already. The quality-draft Edge Function calls it, then starts
--    .github/workflows/quality-draft.yml; the 4-hourly collection drafts whatever still waits (the safety net).
-- 3. quality_drafts(): the latest draft of every record, for the Quality tab (everyone signed in).
-- The collectors claim, finish and fail a draft on their direct connection (the owner): no function is needed.

create table quality_draft (
  id                 uuid primary key default gen_random_uuid(),
  record_kind        text not null check (record_kind in ('deviation', 'observation')),
  record_id          uuid not null,
  status             text not null default 'queued' check (status in ('queued', 'drafting', 'ready', 'failed')),
  root_cause         text,
  corrective_action  text,
  preventive_action  text,
  to_check           text,
  model              text,
  error              text,
  attempts           int not null default 0,
  asked_by           uuid not null references person(id),
  asked_at           timestamptz not null default now(),
  started_at         timestamptz,
  finished_at        timestamptz,
  check (status <> 'ready' or (root_cause is not null and finished_at is not null)),
  check (status <> 'failed' or (error is not null and finished_at is not null))
);
comment on table quality_draft is
  'A drafted root cause and CAPA for a deviation or an audit observation, asked for by a reviewer (0109). Text only: it changes no record.';
create unique index quality_draft_one_waiting on quality_draft (record_kind, record_id)
  where status in ('queued', 'drafting');
create index on quality_draft (record_kind, record_id, asked_at desc);

create trigger audit_quality_draft after insert or update or delete on quality_draft
  for each row execute function audit_row();
alter table quality_draft enable row level security;
create policy quality_draft_read on quality_draft for select to authenticated using (my_role() is not null);
revoke all on quality_draft from public, anon;
revoke insert, update, delete, truncate on quality_draft from authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on quality_draft from service_role';
  end if;
end $$;

-- Ask for a draft. Returns the draft's id (the one already waiting, if any).
create function quality_draft_ask(p_kind text, p_id uuid) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := quality_require_writer();
  v_closed boolean;
  v_id     uuid;
begin
  if p_kind = 'deviation' then
    select status = 'closed' into v_closed from deviation where id = p_id;
  elsif p_kind = 'observation' then
    select a.status = 'closed' into v_closed
      from audit_observation o join audit a on a.id = o.audit_id where o.id = p_id;
  else
    raise exception 'A draft is for a deviation or an audit observation.' using errcode = '22023';
  end if;
  if v_closed is null then
    raise exception 'That record does not exist.' using errcode = '22023';
  end if;
  if v_closed then
    raise exception 'A closed record takes no new draft.' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtext('quality_draft:' || p_kind), hashtext(p_id::text));
  select id into v_id from quality_draft
   where record_kind = p_kind and record_id = p_id and status in ('queued', 'drafting');
  if v_id is not null then
    return v_id;
  end if;
  insert into quality_draft (record_kind, record_id, asked_by) values (p_kind, p_id, v_person) returning id into v_id;
  return v_id;
end $$;

-- The latest draft of every record: [{id, record_kind, record_id, status, root_cause, corrective_action,
-- preventive_action, to_check, model, error, asked_by (a name), asked_at, finished_at}].
create function quality_drafts() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the quality records.' using errcode = '42501';
  end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'id', q.id, 'record_kind', q.record_kind, 'record_id', q.record_id, 'status', q.status,
             'root_cause', q.root_cause, 'corrective_action', q.corrective_action,
             'preventive_action', q.preventive_action, 'to_check', q.to_check, 'model', q.model, 'error', q.error,
             'asked_by', p.full_name, 'asked_at', q.asked_at, 'finished_at', q.finished_at)
           order by q.asked_at desc)
      from (select distinct on (record_kind, record_id) *
              from quality_draft
             order by record_kind, record_id, asked_at desc, id) q
      left join person p on p.id = q.asked_by), '[]'::jsonb);
end $$;

revoke all on function quality_draft_ask(text, uuid), quality_drafts() from public, anon;
grant execute on function quality_draft_ask(text, uuid), quality_drafts() to authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function quality_draft_ask(text, uuid), quality_drafts() from service_role';
  end if;
end $$;
