-- PHAROS — individual case reports: intake, automatic reading, confirmation, the clock, and the E2B(R3) file
-- (2026-11-06).
--
-- A case comes in three ways:
--   upload  a reviewer drops the source document (PDF, photo, Word file, saved email, text) on the Cases screen;
--           the case-intake function stores it in the archive under sha256/ and calls create_upload_case();
--   paper   a reviewer opens a case from a literature paper PHAROS found (create_paper_case());
--   email   a member of the team forwards the report to the PHAROS mailbox with CASE in the subject; the
--           collector (collectors/cases/mail.py) stores the message under inbound/ and inserts the case itself.
-- The collector (collectors/cases/read.py) then reads the document and fills the case form: patient, reporter,
-- products, reactions, seriousness and a narrative, each with the words of the document that support it. What
-- the reader returned is kept unchanged in `extracted`; `data` is the case as the team keeps it. Nothing is
-- reported on the reader's word: a reviewer checks the form against the document and confirms it, and
-- confirm_case() refuses a case without the four minimum criteria of GVP Module VI (an identifiable patient,
-- an identifiable reporter, a suspect product, a reaction).
--
-- The clock: day zero is the Cairo day the company first knew of the case (the upload's day chosen by the
-- reviewer, the day PHAROS found the paper, the day the email arrived). A serious case is due 15 days later, a
-- non-serious one 90; until a reviewer says which, the case counts as serious.
--
-- Every step is one row in case_event, which is append-only like signal_event: it is the evidence an inspector
-- reads, and it keeps a copy of the form at each save and confirmation. safety_case carries only the current
-- state and is written by the functions below (as the signed-in person) or by the collector, never by the app
-- directly. Two people changing one case at once: each function takes the updated_at the person saw, and a
-- change made from an older view is refused (SQLSTATE PH409, message prefix STALE_CASE).
--
-- The E2B(R3) file is made on request (ask_case_e2b()) by the collector (collectors/cases/e2b.py) for a confirmed
-- or sent case, archived under reports/cases/, and its SHA-256 kept here.

create type case_origin as enum ('upload','paper','email');
create type case_status as enum ('queued','reading','to_confirm','confirmed','sent','not_valid','failed');
create type case_step   as enum ('received','read','read_failed','read_again','saved','confirmed','not_valid',
                                 'sent','reopened','e2b_asked','e2b_made','e2b_failed','note');

create sequence case_number;

create table safety_case (
  id                uuid primary key default gen_random_uuid(),
  ref               text unique not null,                  -- CASE-2026-001, the name people use
  origin            case_origin not null,
  status            case_status not null default 'queued',
  ingredient_id     uuid references ingredient(id),
  document_id       uuid unique references document(id),   -- the paper (origin paper)
  inbound_email_id  uuid unique references inbound_email(id),
  file_name         text,
  mime              text,
  sha256            text,                                  -- of the source file as archived
  r2_key            text,
  bytes             int,
  day_zero          date not null,
  serious           boolean,                               -- null: not decided yet (counts as serious)
  extracted         jsonb,                                 -- what the reader returned, never changed by people
  data              jsonb not null default '{}'::jsonb,    -- the case form as the team keeps it
  reader_model      text,
  read_at           timestamptz,
  read_error        text,
  read_attempts     int not null default 0,
  confirmed_by      uuid references person(id),
  confirmed_at      timestamptz,
  sent_on           date,
  authority_ref     text,
  e2b_status        text check (e2b_status in ('queued','made','failed')),
  e2b_error         text,
  e2b_r2_key        text,
  e2b_sha256        text,
  e2b_at            timestamptz,
  created_by        uuid references person(id),            -- null: the collector (email)
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  check (origin <> 'upload' or (r2_key is not null and sha256 is not null)),
  check (origin <> 'paper'  or document_id is not null),
  check (origin <> 'email'  or inbound_email_id is not null),
  check (octet_length(data::text) <= 200000)
);
create index on safety_case (status);
create index on safety_case (ingredient_id);
create index on safety_case (created_at desc);

-- Append-only: the case's history is evidence.
create table case_event (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references safety_case(id) on delete cascade,
  step         case_step not null,
  from_status  case_status,
  to_status    case_status not null,
  comment      text,
  data         jsonb,                                       -- the form as saved or confirmed
  person_id    uuid references person(id),                  -- null: PHAROS itself (reading, the E2B file)
  created_at   timestamptz not null default now()
);
create index on case_event (case_id, created_at);

create function case_event_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'case_event is append-only';
end $$;
create trigger case_event_no_update before update or delete on case_event
  for each row execute function case_event_immutable();

create trigger audit_safety_case after insert or update or delete on safety_case
  for each row execute function audit_row();

alter table safety_case enable row level security;
alter table case_event  enable row level security;
create policy safety_case_read on safety_case for select to authenticated using (my_role() is not null);
create policy case_event_read  on case_event  for select to authenticated using (my_role() is not null);
-- No write policies: only the functions below (and the collector) write.
revoke insert, update, delete, truncate on safety_case, case_event from anon, authenticated;
revoke all on sequence case_number from anon, authenticated;

-- ───────────────────────────── helpers ─────────────────────────────
create function case_cairo_today() returns date language sql stable as $$
  select (now() at time zone 'Africa/Cairo')::date
$$;

-- The day the case is due at the authority: 15 days after day zero, 90 when a reviewer has said it is not serious.
create function case_due(p_day_zero date, p_serious boolean) returns date language sql immutable as $$
  select p_day_zero + case when p_serious is false then 90 else 15 end
$$;

-- Which of the four minimum criteria (GVP Module VI) the form does not meet yet: patient, reporter, product,
-- reaction. An empty array is a valid case. The same rule is in web/src/features/cases/caseForm.ts and
-- collectors/cases/schema.py.
create function case_missing(p jsonb) returns text[] language sql immutable as $$
  with f as (
    select coalesce(p, '{}'::jsonb) as d
  ), t as (
    select d,
           case when jsonb_typeof(d -> 'products')  = 'array' then d -> 'products'  else '[]'::jsonb end as products,
           case when jsonb_typeof(d -> 'reactions') = 'array' then d -> 'reactions' else '[]'::jsonb end as reactions
      from f
  )
  select array_remove(array[
    case when coalesce(nullif(trim(d #>> '{patient,initials}'), ''), nullif(trim(d #>> '{patient,age_value}'), ''),
                       nullif(trim(d #>> '{patient,age_group}'), ''), nullif(trim(d #>> '{patient,sex}'), ''),
                       nullif(trim(d #>> '{patient,birth_date}'), '')) is null
         then 'patient' end,
    case when coalesce(nullif(trim(d #>> '{reporter,name}'), ''), nullif(trim(d #>> '{reporter,qualification}'), ''),
                       nullif(trim(d #>> '{reporter,organisation}'), ''), nullif(trim(d #>> '{reporter,email}'), ''),
                       nullif(trim(d #>> '{reporter,phone}'), ''), nullif(trim(d ->> 'literature_reference'), '')) is null
         then 'reporter' end,
    case when not exists (select 1 from jsonb_array_elements(products) e
                           where e ->> 'role' = 'suspect' and nullif(trim(e ->> 'name'), '') is not null)
         then 'product' end,
    case when not exists (select 1 from jsonb_array_elements(reactions) e
                           where nullif(trim(e ->> 'verbatim'), '') is not null)
         then 'reaction' end
  ], null)
  from t
$$;

create function case_require_reviewer() returns uuid language plpgsql stable security definer
set search_path = public as $$
declare v_person uuid := my_person_id();
begin
  if v_person is null or my_role() not in ('admin','reviewer') then
    raise exception 'Only a reviewer or an administrator can change a case.' using errcode = '42501';
  end if;
  return v_person;
end $$;

create function case_new_ref() returns text language sql volatile security definer set search_path = public as $$
  select 'CASE-' || to_char(case_cairo_today(), 'YYYY') || '-' || lpad(nextval('case_number')::text, 3, '0')
$$;

-- Locks the case and checks the person saw its latest state.
create function case_lock(p_case uuid, p_seen timestamptz) returns safety_case language plpgsql
security definer set search_path = public as $$
declare v safety_case%rowtype;
begin
  select * into v from safety_case where id = p_case for update;
  if v.id is null then raise exception 'That case does not exist.' using errcode = '22023'; end if;
  if p_seen is null or v.updated_at is distinct from p_seen then
    raise exception 'STALE_CASE: someone else changed % a moment ago.', v.ref
      using errcode = 'PH409', hint = 'Reload the case and look again.';
  end if;
  return v;
end $$;

create function case_check_form(p_data jsonb, p_ingredient uuid) returns void language plpgsql stable
security definer set search_path = public as $$
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'The case form is not valid.' using errcode = '22023';
  end if;
  if octet_length(p_data::text) > 200000 then
    raise exception 'The case form is too long.' using errcode = '22023';
  end if;
  if p_ingredient is not null and not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = '22023';
  end if;
end $$;

-- ───────────────────────────── a case from an uploaded document ─────────────────────────────
-- The case-intake function has already stored the file under sha256/<2>/<sha256>; the collector checks the
-- archived bytes against p_sha256 before it reads them.
create function create_upload_case(p_file_name text, p_mime text, p_sha256 text, p_bytes int, p_day_zero date,
                                   p_ingredient uuid default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v_id     uuid;
  v_name   text := nullif(left(trim(coalesce(p_file_name, '')), 200), '');
begin
  if p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'The file''s SHA-256 is not valid.' using errcode = '22023';
  end if;
  if p_mime is null or p_mime not in ('application/pdf','image/png','image/jpeg','image/gif','image/webp','message/rfc822','text/plain',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document') then
    raise exception 'PHAROS reads PDF, photos (PNG, JPEG, GIF, WebP), Word (.docx), saved emails (.eml) and text files.'
      using errcode = '22023';
  end if;
  if p_bytes is null or p_bytes <= 0 or p_bytes > 10 * 1024 * 1024 then
    raise exception 'A case document is at most 10 MB.' using errcode = '22023';
  end if;
  if p_day_zero is null or p_day_zero > case_cairo_today() or p_day_zero < case_cairo_today() - 366 then
    raise exception 'Day zero is the day the company received the report: today or within the last year.'
      using errcode = '22023';
  end if;
  perform case_check_form('{}'::jsonb, p_ingredient);

  insert into safety_case (ref, origin, status, ingredient_id, file_name, mime, sha256, r2_key, bytes, day_zero, created_by)
  values (case_new_ref(), 'upload', 'queued', p_ingredient, coalesce(v_name, 'document'), p_mime, p_sha256,
          'sha256/' || left(p_sha256, 2) || '/' || p_sha256, p_bytes, p_day_zero, v_person)
  returning id into v_id;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (v_id, 'received', null, 'queued', coalesce(v_name, 'document'), v_person);
  return v_id;
end $$;

-- ───────────────────────────── a case from a literature paper ─────────────────────────────
-- Day zero is the Cairo day PHAROS found the paper, as on the Ingredients screen (0044). The ingredient is the
-- paper's own when its notice names exactly one.
create function create_paper_case(p_document uuid) returns uuid language plpgsql security definer
set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v_doc    document%rowtype;
  v_kind   text;
  v_ing    uuid;
  v_id     uuid;
begin
  select * into v_doc from document where id = p_document;
  if v_doc.id is null then raise exception 'That paper does not exist.' using errcode = '22023'; end if;
  select kind::text into v_kind from source where id = v_doc.source_id;
  if v_kind is distinct from 'literature' then
    raise exception 'Only a paper from the literature watch can open a case this way.' using errcode = '22023';
  end if;
  select id into v_id from safety_case where document_id = p_document;
  if v_id is not null then
    raise exception 'This paper already has a case.' using errcode = '23505';
  end if;
  select case when count(distinct ii.ingredient_id) = 1 then min(ii.ingredient_id::text)::uuid end into v_ing
    from issue_document idd
    join issue_ingredient ii on ii.issue_id = idd.issue_id
   where idd.document_id = p_document and idd.method <> 'suggested';

  insert into safety_case (ref, origin, status, ingredient_id, document_id, file_name, day_zero, created_by,
                           data)
  values (case_new_ref(), 'paper', 'queued', v_ing, p_document, left(v_doc.title_orig, 200),
          (v_doc.first_seen_at at time zone 'Africa/Cairo')::date, v_person,
          jsonb_build_object('report_type', 'literature'))
  returning id into v_id;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (v_id, 'received', null, 'queued', left(v_doc.title_orig, 500), v_person);
  return v_id;
end $$;

-- ───────────────────────────── the form ─────────────────────────────
-- Saves the form without confirming it. A case that could not be read is filled in by hand the same way.
create function save_case(p_case uuid, p_seen timestamptz, p_data jsonb, p_serious boolean, p_ingredient uuid,
                          p_comment text default null)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if v.status not in ('to_confirm','failed') then
    raise exception 'Only a case waiting for confirmation can be changed. Reopen it first.' using errcode = '22023';
  end if;
  perform case_check_form(p_data, p_ingredient);
  update safety_case set data = p_data, serious = p_serious, ingredient_id = p_ingredient, status = 'to_confirm',
                         updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, data, person_id)
  values (p_case, 'saved', v.status, 'to_confirm', nullif(trim(p_comment), ''), p_data, v_person);
  return v_now;
end $$;

-- Confirms the case: the reviewer has checked the form against the document. It must meet the four minimum
-- criteria, name its ingredient and say whether it is serious.
create function confirm_case(p_case uuid, p_seen timestamptz, p_data jsonb, p_serious boolean, p_ingredient uuid,
                             p_comment text default null)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person  uuid := case_require_reviewer();
  v         safety_case%rowtype := case_lock(p_case, p_seen);
  v_missing text[];
  v_now     timestamptz := clock_timestamp();
begin
  if v.status not in ('to_confirm','failed') then
    raise exception 'Only a case waiting for confirmation can be confirmed.' using errcode = '22023';
  end if;
  perform case_check_form(p_data, p_ingredient);
  v_missing := case_missing(p_data);
  if cardinality(v_missing) > 0 then
    raise exception 'Not a valid case yet: % missing.', array_to_string(v_missing, ', ') using errcode = '22023';
  end if;
  if p_ingredient is null then
    raise exception 'Choose the ingredient the case is about.' using errcode = '22023';
  end if;
  if p_serious is null then
    raise exception 'Say whether the case is serious.' using errcode = '22023';
  end if;
  update safety_case set data = p_data, serious = p_serious, ingredient_id = p_ingredient, status = 'confirmed',
                         confirmed_by = v_person, confirmed_at = v_now, updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, data, person_id)
  values (p_case, 'confirmed', v.status, 'confirmed', nullif(trim(p_comment), ''), p_data, v_person);
  return v_now;
end $$;

-- Not a valid case (or not ours): closed with the reason.
create function case_not_valid(p_case uuid, p_seen timestamptz, p_comment text)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if nullif(trim(p_comment), '') is null then
    raise exception 'Say why this is not a valid case.' using errcode = '22023';
  end if;
  if v.status not in ('to_confirm','failed','confirmed') then
    raise exception 'Only a case not yet sent can be closed as not valid.' using errcode = '22023';
  end if;
  update safety_case set status = 'not_valid', updated_at = v_now where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (p_case, 'not_valid', v.status, 'not_valid', trim(p_comment), v_person);
  return v_now;
end $$;

-- Sent to the authority: the day and its reference (the E2B acknowledgement, or the email's).
create function case_sent(p_case uuid, p_seen timestamptz, p_sent_on date, p_ref text, p_comment text default null)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if v.status <> 'confirmed' then
    raise exception 'Only a confirmed case can be marked as sent.' using errcode = '22023';
  end if;
  if p_sent_on is null or p_sent_on > case_cairo_today() or p_sent_on < v.day_zero then
    raise exception 'The day it was sent is between day zero and today.' using errcode = '22023';
  end if;
  if nullif(trim(p_ref), '') is null then
    raise exception 'Give the authority''s reference, or the subject of the email it went with.' using errcode = '22023';
  end if;
  update safety_case set status = 'sent', sent_on = p_sent_on, authority_ref = left(trim(p_ref), 200), updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (p_case, 'sent', v.status, 'sent',
          left(trim(p_ref), 200) || coalesce(' · ' || nullif(trim(p_comment), ''), ''), v_person);
  return v_now;
end $$;

-- Reopens a confirmed, sent or closed case, for new information (a follow-up) or a correction. New information
-- starts a new clock: p_day_zero is the day it arrived (unchanged when null).
create function reopen_case(p_case uuid, p_seen timestamptz, p_comment text, p_day_zero date default null)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if nullif(trim(p_comment), '') is null then
    raise exception 'Say why the case is reopened.' using errcode = '22023';
  end if;
  if v.status not in ('confirmed','sent','not_valid') then
    raise exception 'This case is already open.' using errcode = '22023';
  end if;
  if p_day_zero is not null and (p_day_zero > case_cairo_today() or p_day_zero < v.day_zero) then
    raise exception 'The new day zero is between the first one and today.' using errcode = '22023';
  end if;
  update safety_case set status = 'to_confirm', day_zero = coalesce(p_day_zero, day_zero), updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (p_case, 'reopened', v.status, 'to_confirm',
          trim(p_comment) || case when p_day_zero is not null and p_day_zero <> v.day_zero
                                  then ' · new day zero ' || to_char(p_day_zero, 'YYYY-MM-DD') else '' end,
          v_person);
  return v_now;
end $$;

-- A note on the record.
create function case_note(p_case uuid, p_comment text) returns void language plpgsql security definer
set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v_status case_status;
begin
  if nullif(trim(p_comment), '') is null then raise exception 'Write the note first.' using errcode = '22023'; end if;
  select status into v_status from safety_case where id = p_case;
  if v_status is null then raise exception 'That case does not exist.' using errcode = '22023'; end if;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (p_case, 'note', v_status, v_status, left(trim(p_comment), 4000), v_person);
end $$;

-- ───────────────────────────── reading and the E2B file, on request ─────────────────────────────
-- Read the document again (the reader failed, or the form should start again from the document). The form the
-- team saved is kept in case_event; the new reading replaces it on the screen.
create function ask_case_read(p_case uuid, p_seen timestamptz) returns timestamptz language plpgsql
security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if v.status not in ('to_confirm','failed') then
    raise exception 'Only a case waiting for confirmation can be read again.' using errcode = '22023';
  end if;
  update safety_case set status = 'queued', read_error = null, read_attempts = 0, updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, person_id)
  values (p_case, 'read_again', v.status, 'queued', v_person);
  return v_now;
end $$;

create function ask_case_e2b(p_case uuid, p_seen timestamptz) returns timestamptz language plpgsql
security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
begin
  if v.status not in ('confirmed','sent') then
    raise exception 'Confirm the case first: the E2B file is made from the confirmed form.' using errcode = '22023';
  end if;
  if v.e2b_status = 'queued' then
    raise exception 'The E2B file is already being made.' using errcode = '22023';
  end if;
  update safety_case set e2b_status = 'queued', e2b_error = null, updated_at = v_now where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, person_id)
  values (p_case, 'e2b_asked', v.status, v.status, v_person);
  return v_now;
end $$;

-- ───────────────────────────── the list ─────────────────────────────
create view v_case_table with (security_invoker = true) as
select
  c.id, c.ref, c.origin, c.status, c.ingredient_id,
  ing.inn_en                                                        as ingredient,
  c.file_name, c.day_zero, c.serious,
  case_due(c.day_zero, c.serious)                                   as due,
  (c.status in ('queued','reading','to_confirm','failed','confirmed')
   and case_due(c.day_zero, c.serious) < case_cairo_today())         as overdue,
  c.sent_on, c.authority_ref,
  nullif(concat_ws(' · ', c.data #>> '{patient,initials}',
                   nullif(concat_ws(' ', c.data #>> '{patient,age_value}', c.data #>> '{patient,age_unit}'), ''),
                   c.data #>> '{patient,sex}'), '')                  as patient,
  (select string_agg(e ->> 'verbatim', '; ')
     from jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                    then c.data -> 'reactions' else '[]'::jsonb end) e)  as reactions,
  case_missing(c.data)                                              as missing,
  c.e2b_status, c.created_at, c.updated_at
from safety_case c
left join ingredient ing on ing.id = c.ingredient_id;

revoke all on function case_require_reviewer(), case_new_ref(), case_lock(uuid, timestamptz),
  case_check_form(jsonb, uuid),
  create_upload_case(text, text, text, int, date, uuid), create_paper_case(uuid),
  save_case(uuid, timestamptz, jsonb, boolean, uuid, text), confirm_case(uuid, timestamptz, jsonb, boolean, uuid, text),
  case_not_valid(uuid, timestamptz, text), case_sent(uuid, timestamptz, date, text, text),
  reopen_case(uuid, timestamptz, text, date), case_note(uuid, text),
  ask_case_read(uuid, timestamptz), ask_case_e2b(uuid, timestamptz)
  from public, anon;
grant execute on function
  create_upload_case(text, text, text, int, date, uuid), create_paper_case(uuid),
  save_case(uuid, timestamptz, jsonb, boolean, uuid, text), confirm_case(uuid, timestamptz, jsonb, boolean, uuid, text),
  case_not_valid(uuid, timestamptz, text), case_sent(uuid, timestamptz, date, text, text),
  reopen_case(uuid, timestamptz, text, date), case_note(uuid, text),
  ask_case_read(uuid, timestamptz), ask_case_e2b(uuid, timestamptz)
  to authenticated;
grant execute on function case_missing(jsonb), case_due(date, boolean), case_cairo_today() to authenticated;
