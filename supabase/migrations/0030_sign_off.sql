-- PHAROS — electronic sign-off (2026-11-05).
--
-- A person signs a record (the monthly report, or a closed signal) by entering their password again: the
-- signature carries their name and role at that moment, what the signature means (reviewed / approved), the
-- Cairo time from the database clock, and the SHA-256 of the record as it was signed. The table is
-- append-only, so a signature is never changed or removed; when a record changes after it was signed (a
-- report made again, a signal reopened), record_fingerprint() no longer matches and the page says so.
--
-- The password is checked by Supabase Auth, not here: sign_record() accepts a signature only when the
-- caller's token shows a password sign-in in the last five minutes (the "amr" claim), which the page gets by
-- signing in again with the password typed into the signature form.

create type sign_kind    as enum ('monthly_report', 'signal');
create type sign_meaning as enum ('reviewed', 'approved');

create table sign_off (
  id             uuid primary key default gen_random_uuid(),
  record_kind    sign_kind not null,
  record_id      uuid not null,
  record_sha256  text not null,
  meaning        sign_meaning not null,
  person_id      uuid not null references person(id),
  signed_name    text not null,
  signed_role    person_role not null,
  comment        text,
  signed_at      timestamptz not null default now(),
  unique (record_kind, record_id, record_sha256, person_id, meaning)
);
create index on sign_off (record_kind, record_id);

create function sign_off_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'A signature is never changed or removed.';
end $$;
create trigger sign_off_no_change before update or delete on sign_off
  for each row execute function sign_off_immutable();
create trigger audit_sign_off after insert on sign_off for each row execute function audit_row();

alter table sign_off enable row level security;
create policy sign_off_read on sign_off for select to authenticated using (my_role() is not null);
revoke insert, update, delete, truncate on sign_off from anon, authenticated;

-- The SHA-256 of a record as it is now: the report's PDF and Excel files; the signal's fields, every step
-- and every notice linked to it. Null when the record does not exist.
create function record_fingerprint(p_kind sign_kind, p_id uuid)
returns text language sql stable security definer set search_path = public as $$
  select case p_kind
    when 'monthly_report' then
      (select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex')
         from monthly_report r where r.id = p_id)
    when 'signal' then
      (select encode(sha256(convert_to(jsonb_build_object(
                'signal', to_jsonb(s) - 'updated_at',
                'events', (select coalesce(jsonb_agg(e.id order by e.created_at, e.id), '[]') from signal_event e where e.signal_id = s.id),
                'issues', (select coalesce(jsonb_agg(si.issue_id order by si.issue_id), '[]') from signal_issue si where si.signal_id = s.id)
              )::text, 'UTF8')), 'hex')
         from signal s where s.id = p_id)
  end
  where my_role() is not null
$$;
revoke all on function record_fingerprint(sign_kind, uuid) from public, anon;
grant execute on function record_fingerprint(sign_kind, uuid) to authenticated;

create function sign_record(p_kind sign_kind, p_id uuid, p_meaning sign_meaning, p_comment text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person  person%rowtype;
  v_sha     text;
  v_fresh   boolean;
  v_id      uuid;
begin
  select * into v_person from person where id = my_person_id();
  if v_person.id is null then
    raise exception 'Sign in to sign.' using errcode = '42501';
  end if;
  if p_kind = 'monthly_report' and v_person.role <> 'admin' then
    raise exception 'Only an administrator can sign the monthly report.' using errcode = '42501';
  end if;
  if p_kind = 'signal' and v_person.role not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can sign a signal.' using errcode = '42501';
  end if;
  select exists (
    select 1 from jsonb_array_elements(coalesce(auth.jwt() -> 'amr', '[]'::jsonb)) a
     where a ->> 'method' = 'password'
       and (a ->> 'timestamp')::bigint >= extract(epoch from now())::bigint - 300
  ) into v_fresh;
  if not v_fresh then
    raise exception 'Enter your password to sign.' using errcode = '28P01';
  end if;
  if p_kind = 'signal' and not exists (select 1 from signal where id = p_id and stage = 'closed') then
    raise exception 'A signal is signed once it is closed.' using errcode = '22023';
  end if;
  v_sha := record_fingerprint(p_kind, p_id);
  if v_sha is null then
    raise exception 'That record does not exist.' using errcode = '22023';
  end if;
  if exists (select 1 from sign_off where record_kind = p_kind and record_id = p_id and record_sha256 = v_sha
                                       and person_id = v_person.id and meaning = p_meaning) then
    raise exception 'You have already signed this record with that meaning.' using errcode = '23505';
  end if;
  insert into sign_off (record_kind, record_id, record_sha256, meaning, person_id, signed_name, signed_role, comment)
  values (p_kind, p_id, v_sha, p_meaning, v_person.id, v_person.full_name, v_person.role,
          nullif(trim(p_comment), ''))
  returning id into v_id;
  return v_id;
end $$;
revoke all on function sign_record(sign_kind, uuid, sign_meaning, text) from public, anon;
grant execute on function sign_record(sign_kind, uuid, sign_meaning, text) to authenticated;
