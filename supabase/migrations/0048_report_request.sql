-- PHAROS — PSUR packs and inspection packs on request (2026-11-06, the QPPV plan, phase 15).
--
-- His decision (6 Nov 2026): a pack is asked for with a button on Reports and built within four hours, by the
-- next collection run. A reviewer or an administrator asks; collectors/report_pack.py builds one request per run
-- from the same database functions as the weekly report, archives the PDF and the Excel file in R2 (bucket lock:
-- never overwritten) with their SHA-256, and tells the person who asked (and the administrators) on Telegram.
--
-- 1. report_request: one row per request. kind 'psur' (one ingredient) or 'inspection' (no ingredient); the Cairo
--    days it covers, both included, at most five years; who asked and when; status queued → building → done or
--    failed, with the reason (error) and how many times the build was started (attempts). When made: the two
--    archive keys and their SHA-256, when, the code that made it (git_sha) and the GitHub Actions run
--    (made_by_run). A member of the team reads every request; nobody writes one from the app except through
--    request_report(); every change is in the audit log. The service key (service_role) holds no right on it,
--    as 0050 did for authority_report: the collector writes on its direct connection (the owner).
-- 2. request_report(p_kind, p_ingredient, p_from, p_to): a reviewer or an administrator asks. The same pack asked
--    for again while it is still waiting or being made returns that request instead of a second one (one queued
--    or building per kind, ingredient and days). A pack already made can be asked for again (a new row).
-- 3. record_fingerprint(): the 'pack' branch (0047 said "not yet") reads report_request: the SHA-256 of
--    pdf_sha256 || ':' || xlsx_sha256, as the weekly and monthly reports. A pack not made yet has no files, so no
--    fingerprint, and sign_record() refuses it ("That record does not exist", 22023). sign_record() is unchanged:
--    a reviewer or an administrator signs a pack ("Reviewed" / "Approved").
-- The archive-url function serves report_request.pdf_r2_key and xlsx_r2_key (supabase/functions/archive-url).

-- ───────────────────────────── 1. the requests ─────────────────────────────
create table report_request (
  id             uuid primary key default gen_random_uuid(),
  kind           text not null check (kind in ('psur', 'inspection')),
  ingredient_id  uuid references ingredient(id),
  from_day       date not null,                     -- Cairo days, both included
  to_day         date not null,
  requested_by   uuid not null references person(id),
  requested_at   timestamptz not null default now(),
  status         text not null default 'queued' check (status in ('queued', 'building', 'done', 'failed')),
  error          text,                              -- why it failed, or a note while it waits
  attempts       int not null default 0,            -- builds started (a build cut short is tried again)
  started_at     timestamptz,                       -- when the latest build started
  pdf_r2_key     text,
  pdf_sha256     text,
  xlsx_r2_key    text,
  xlsx_sha256    text,
  made_at        timestamptz,
  git_sha        text,                              -- the code that made it
  made_by_run    text,                              -- the GitHub Actions run that made it (its address)
  check (from_day <= to_day),
  check (to_day <= (from_day + interval '5 years')::date),
  check ((kind = 'psur') = (ingredient_id is not null)),
  check (status <> 'done' or (pdf_r2_key is not null and pdf_sha256 is not null
                              and xlsx_r2_key is not null and xlsx_sha256 is not null and made_at is not null))
);
comment on table report_request is
  'A PSUR pack or an inspection pack asked for on Reports: built by the next collection run, archived with its SHA-256 (0048).';
create index on report_request (status, requested_at);
-- One waiting request per pack: the same kind, ingredient and days.
create unique index report_request_one_waiting on report_request
  (kind, coalesce(ingredient_id, '00000000-0000-0000-0000-000000000000'::uuid), from_day, to_day)
  where status in ('queued', 'building');

alter table report_request enable row level security;
create policy report_request_read on report_request for select to authenticated using (my_role() is not null);
revoke all on report_request from public, anon;
revoke insert, update, delete, truncate on report_request from authenticated;
create trigger audit_report_request after insert or update or delete on report_request
  for each row execute function audit_row();

-- ───────────────────────────── 2. asking for a pack ─────────────────────────────
create function request_report(p_kind text, p_ingredient uuid, p_from date, p_to date)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_id uuid;
begin
  if my_role() is null or my_role() not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can ask for a pack.' using errcode = '42501';
  end if;
  if p_kind is null or p_kind not in ('psur', 'inspection') then
    raise exception 'Choose a PSUR pack or an inspection pack.' using errcode = '22023';
  end if;
  if p_kind = 'psur' and p_ingredient is null then
    raise exception 'Choose the ingredient of the PSUR pack.' using errcode = '22023';
  end if;
  if p_kind = 'inspection' and p_ingredient is not null then
    raise exception 'An inspection pack covers every ingredient: choose none.' using errcode = '22023';
  end if;
  if p_ingredient is not null and not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose days whose end is on or after their start.' using errcode = '22023';
  end if;
  if p_to > (p_from + interval '5 years')::date then
    raise exception 'A pack covers at most five years.' using errcode = '22023';
  end if;
  if p_from > signal_cairo_today() then
    raise exception 'Choose days that have started: the first day is in the future.' using errcode = '22023';
  end if;

  select id into v_id
    from report_request
   where kind = p_kind and ingredient_id is not distinct from p_ingredient
     and from_day = p_from and to_day = p_to and status in ('queued', 'building');
  if v_id is not null then
    return v_id;
  end if;
  begin
    insert into report_request (kind, ingredient_id, from_day, to_day, requested_by)
    values (p_kind, p_ingredient, p_from, p_to, my_person_id())
    returning id into v_id;
  exception when unique_violation then
    -- asked for at the same moment by someone else: the one request
    select id into v_id
      from report_request
     where kind = p_kind and ingredient_id is not distinct from p_ingredient
       and from_day = p_from and to_day = p_to and status in ('queued', 'building');
  end;
  return v_id;
end $$;
revoke all on function request_report(text, uuid, date, date) from public, anon;
grant execute on function request_report(text, uuid, date, date) to authenticated;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on report_request from service_role';
    execute 'revoke all on function request_report(text, uuid, date, date) from service_role';
  end if;
end $$;

-- ───────────────────────────── 3. the fingerprint of a pack ─────────────────────────────
-- As 0047, with the pack branch reading report_request.
create or replace function record_fingerprint(p_kind sign_kind, p_id uuid)
returns text language plpgsql stable security definer set search_path = public as $$
declare
  v_sha text;
begin
  if my_role() is null then
    return null;
  end if;
  case p_kind
    when 'monthly_report' then
      select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex') into v_sha
        from monthly_report r where r.id = p_id;
    when 'weekly_report' then
      select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex') into v_sha
        from weekly_report r where r.id = p_id;
    when 'signal' then
      select encode(sha256(convert_to(jsonb_build_object(
                'signal', to_jsonb(s) - 'updated_at',
                'events', (select coalesce(jsonb_agg(e.id order by e.created_at, e.id), '[]') from signal_event e where e.signal_id = s.id),
                'issues', (select coalesce(jsonb_agg(si.issue_id order by si.issue_id), '[]') from signal_issue si where si.signal_id = s.id)
              )::text, 'UTF8')), 'hex') into v_sha
        from signal s where s.id = p_id;
    when 'pack' then
      -- null until the pack is made (no files yet): a pack is signed once it exists
      select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex') into v_sha
        from report_request r where r.id = p_id;
  end case;
  return v_sha;
end $$;
revoke all on function record_fingerprint(sign_kind, uuid) from public, anon;
grant execute on function record_fingerprint(sign_kind, uuid) to authenticated;
