-- PHAROS — drug classes from the ATC code, and the past 12 months checked again when the words change
-- (2026-11-06, after Dr Sama's review).
--
-- 1. A drug class says where it came from: 'atc' (the daily job made it from the ingredient's ATC code,
--    level 4, e.g. J01MA Fluoroquinolones, with its words from Wikidata) or 'hand' (the NSAID seed). An
--    administrator adds or removes a class word and confirms the class; the confirmation names her and the
--    date. Class words record where they came from and who added them.
-- 2. A newly added ingredient, a new or changed search word, or a new class word used to be looked for only
--    in notices that arrived afterwards. Every ingredient word and class word now carries changed_at (set by
--    the database whenever the word, its language, its matching or its exclusions change) and rematched_at
--    (set by collectors/rematch.py once the stored notices of the last 12 months were checked again with it).
--    A word is due while rematched_at is null or older than changed_at. rematch_job keeps the progress of
--    that check so that it resumes where the last run stopped; what it finds is history (is_backfill):
--    no Telegram message and no digest.
-- The words already in place at the last 12-month backfill were checked by it and are marked as done;
-- anything added after it (levofloxacin, 5 Nov 2026 21:36 UTC) stays due.

-- ───────────────────────────── drug classes ─────────────────────────────
alter table drug_class
  add column origin        text not null default 'hand' check (origin in ('atc', 'hand')),
  add column wikidata_qid  text,
  add column confirmed_by  uuid references person(id),
  add column confirmed_at  timestamptz,
  add column created_at    timestamptz not null default now();

create trigger audit_drug_class after insert or update or delete on drug_class
  for each row execute function audit_row();

alter table class_term
  add column source        text,
  add column added_by      uuid references person(id),
  add column changed_at    timestamptz not null default now(),
  add column rematched_at  timestamptz;
update class_term set source = 'seed' where source is null;

alter table ingredient_term
  add column changed_at    timestamptz not null default now(),
  add column rematched_at  timestamptz;

-- A new word, or a change to what it finds (the word, its language, its matching, its exclusions), makes it
-- due for the check of the past. Anything else (who verified it, its country) leaves changed_at alone.
create function term_changed_at() returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT'
     or new.term is distinct from old.term
     or new.lang is distinct from old.lang
     or new.mode is distinct from old.mode
     or new.exclusions is distinct from old.exclusions then
    new.changed_at := now();
  end if;
  return new;
end $$;
create trigger ingredient_term_changed_at before insert or update on ingredient_term
  for each row execute function term_changed_at();
create trigger class_term_changed_at before insert or update on class_term
  for each row execute function term_changed_at();

-- A paused ingredient was not looked for while paused: watching it again checks the past again.
create function ingredient_watched_again() returns trigger language plpgsql set search_path = public as $$
begin
  if new.active and not old.active then
    update ingredient_term set changed_at = now() where ingredient_id = new.id;
  end if;
  return new;
end $$;
create trigger ingredient_watched_again after update of active on ingredient
  for each row execute function ingredient_watched_again();

-- The words the last 12-month backfill already looked for are done; the ones added since stay due.
with last_backfill as (select max(started_at) as at from run where trigger = 'backfill')
update ingredient_term t
   set rematched_at = t.changed_at
  from ingredient i, last_backfill b
 where i.id = t.ingredient_id
   and b.at is not null
   and i.created_at < b.at
   and (t.verified_at is null or t.verified_at < b.at);

with last_backfill as (select max(started_at) as at from run where trigger = 'backfill')
update class_term ct
   set rematched_at = ct.changed_at
  from last_backfill b
 where b.at is not null
   and ct.source = 'seed';

-- ───────────────────────────── the check of the past ─────────────────────────────
create table rematch_job (
  id                   uuid primary key default gen_random_uuid(),
  trigger              text not null default 'daily' check (trigger in ('daily', 'manual')),
  started_at           timestamptz not null default now(),
  since                date not null,                 -- the oldest notice date checked
  ingredient_term_ids  uuid[] not null default '{}',
  class_term_ids       uuid[] not null default '{}',
  cursor_document_id   uuid,                          -- the last notice checked (in id order)
  documents_checked    int not null default 0,
  documents_reread     int not null default 0,        -- read again from the archived original
  documents_matched    int not null default 0,
  issues_created       int not null default 0,
  finished_at          timestamptz
);
-- One check at a time: a new one starts only when the last one finished.
create unique index rematch_job_one_open on rematch_job ((true)) where finished_at is null;

alter table rematch_job enable row level security;
create policy rematch_job_read on rematch_job for select to authenticated using (my_role() is not null);
revoke insert, update, delete, truncate on rematch_job from anon, authenticated;

-- ───────────────────────────── class words and confirmation (administrators) ─────────────────────────────
create function add_class_term(p_class uuid, p_lang text, p_term text, p_mode match_mode default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_term  text := btrim(coalesce(p_term, ''));
  v_lang  text := lower(btrim(coalesce(p_lang, '')));
  v_mode  match_mode;
  v_id    uuid;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change the words of a drug class.' using errcode = '42501';
  end if;
  if not exists (select 1 from drug_class where id = p_class) then
    raise exception 'That drug class does not exist.' using errcode = 'P0002';
  end if;
  if char_length(v_term) < 2 or char_length(v_term) > 200 then
    raise exception 'A class word must be 2 to 200 characters long.' using errcode = '22023';
  end if;
  if v_lang !~ '^[a-z]{2,3}(-[a-z0-9]{2,8})?$' then
    raise exception 'Choose the language of the word.' using errcode = '22023';
  end if;
  -- Japanese, Korean and Chinese are matched anywhere in the text; the others by word start.
  v_mode := coalesce(p_mode, case when split_part(v_lang, '-', 1) in ('ja', 'ko', 'zh')
                                  then 'substring' else 'stem' end::match_mode);
  insert into class_term (class_id, lang, term, mode, source, added_by)
  values (p_class, v_lang, v_term, v_mode, 'manual', my_person_id())
  on conflict (class_id, lang, term) do update set mode = excluded.mode
  returning id into v_id;
  return v_id;
end $$;

create function remove_class_term(p_term uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change the words of a drug class.' using errcode = '42501';
  end if;
  delete from class_term where id = p_term;
  if not found then
    raise exception 'That class word is no longer there.' using errcode = 'P0002';
  end if;
end $$;

-- Records that the signed-in administrator checked the class and its words, with the database time.
create function confirm_drug_class(p_class uuid) returns timestamptz
language plpgsql security definer set search_path = public as $$
declare
  v_at timestamptz;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can confirm a drug class.' using errcode = '42501';
  end if;
  update drug_class set confirmed_by = my_person_id(), confirmed_at = now()
   where id = p_class
  returning confirmed_at into v_at;
  if v_at is null then
    raise exception 'That drug class does not exist.' using errcode = 'P0002';
  end if;
  return v_at;
end $$;

revoke all on function add_class_term(uuid, text, text, match_mode) from public, anon;
revoke all on function remove_class_term(uuid) from public, anon;
revoke all on function confirm_drug_class(uuid) from public, anon;
grant execute on function add_class_term(uuid, text, text, match_mode) to authenticated;
grant execute on function remove_class_term(uuid) to authenticated;
grant execute on function confirm_drug_class(uuid) to authenticated;
