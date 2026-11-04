-- PHAROS (Pharmaceutical Alerts & Regulatory Observation System) — core schema.
-- Every regulator is screened in its own language; nothing here stores a translation.
-- The collectors write with the service role (direct Postgres connection); the web app reads and
-- writes as a signed-in person under row-level security. The public (anon) key reads nothing.

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ───────────────────────────── enums ─────────────────────────────
create type source_kind     as enum ('safety','recall','spc','literature');
create type source_channel  as enum ('rss','atom','json','api','html','browser','email');
create type source_schedule as enum ('4h','12h','daily','weekly','monthly');
create type source_health   as enum ('unknown','ok','degraded','down','blocked');
create type source_origin   as enum ('catalogue','user');
create type term_kind       as enum ('inn','salt','brand','code','synonym');
create type match_mode      as enum ('stem','exact','substring');
create type doc_type        as enum ('dhpc','safety_alert','safety_update','recall','psusa','label_change',
                                     'signal','newsletter','literature','other');
create type extraction_kind as enum ('html','text','ocr','none');
create type match_field     as enum ('structured','title','body','attachment');
create type match_conf      as enum ('high','possible');
create type issue_status    as enum ('new','reviewed','relevant','not_relevant');
create type link_kind       as enum ('anchor','copy');
create type link_method     as enum ('auto','suggested','manual');
create type person_role     as enum ('admin','reviewer','reader');
create type sub_kind        as enum ('ingredient','class_digest','admin_health');
create type notif_kind      as enum ('immediate','digest','health','report');
create type run_trigger     as enum ('cron','backfill','probe','manual');

-- ───────────────────────────── people ─────────────────────────────
create table person (
  id                 uuid primary key default gen_random_uuid(),
  auth_user_id       uuid unique references auth.users(id) on delete set null,
  full_name          text not null,
  email              text unique,
  role               person_role not null default 'reader',
  telegram_chat_id   bigint unique,
  telegram_linked_at timestamptz,
  active             boolean not null default true,
  created_at         timestamptz not null default now()
);

-- ───────────────────────── ingredients & terms ─────────────────────────
create table ingredient (
  id            uuid primary key default gen_random_uuid(),
  inn_en        text not null,
  atc_code      text unique,                      -- identity anchor, e.g. lornoxicam = M01AC05
  wikidata_qid  text unique,
  rxcui         text,
  active        boolean not null default true,
  confirmed_by  uuid references person(id),
  confirmed_at  timestamptz,
  created_at    timestamptz not null default now()
);

create table ingredient_term (
  id             uuid primary key default gen_random_uuid(),
  ingredient_id  uuid not null references ingredient(id) on delete cascade,
  lang           text not null,                   -- BCP-47: en, de, fr, fi, ja, ko, ar …
  country_code   text,                            -- ISO-3166 alpha-2 when country-specific (brands)
  term           text not null,
  kind           term_kind not null default 'inn',
  mode           match_mode not null default 'stem',
  exclusions     text[] not null default '{}',    -- e.g. {tenoxicam, meloxicam}
  source         text,                            -- wikidata, cima, bdpm, manual …
  verified_by    uuid references person(id),
  verified_at    timestamptz,
  unique (ingredient_id, lang, term)
);

create table drug_class (
  id       uuid primary key default gen_random_uuid(),
  code     text unique not null,                  -- NSAID
  name_en  text not null
);

create table class_term (
  id          uuid primary key default gen_random_uuid(),
  class_id    uuid not null references drug_class(id) on delete cascade,
  lang        text not null,
  term        text not null,
  mode        match_mode not null default 'stem',
  exclusions  text[] not null default '{}',
  unique (class_id, lang, term)
);

create table ingredient_class (
  ingredient_id uuid references ingredient(id) on delete cascade,
  class_id      uuid references drug_class(id) on delete cascade,
  primary key (ingredient_id, class_id)
);

-- Combination products (phase 2): a product is watched through each of its ingredients.
create table product (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  mah        text,
  created_at timestamptz not null default now()
);
create table product_ingredient (
  product_id    uuid references product(id) on delete cascade,
  ingredient_id uuid references ingredient(id) on delete cascade,
  primary key (product_id, ingredient_id)
);

-- ───────────────────────── regulators & sources ─────────────────────────
create table regulator (
  id            text primary key,                 -- EMA, BFARM, PMDA …
  country_code  text not null,                    -- EU for EMA
  country_name  text not null,
  name          text not null,                    -- official name as the regulator writes it
  languages     text[] not null,
  homepage      text
);

create table source (
  id                    text primary key,         -- ema-dhpc, bfarm-rhb, pmda-revisions …
  regulator_id          text not null references regulator(id),
  kind                  source_kind not null,
  channel               source_channel not null,
  url                   text not null,
  parser                text not null,            -- module name under collectors/parsers
  languages             text[] not null,
  schedule              source_schedule not null default '4h',
  enabled               boolean not null default true,
  origin                source_origin not null default 'catalogue',
  health                source_health not null default 'unknown',
  consecutive_failures  int not null default 0,
  last_ok_at            timestamptz,
  last_item_at          timestamptz,
  expected_max_gap_days int,                      -- quiet longer than this → degraded
  notes                 text,
  created_by            uuid references person(id),
  created_at            timestamptz not null default now()
);

-- ───────────────────────── runs: the screening log ─────────────────────────
create table run (
  id           uuid primary key default gen_random_uuid(),
  trigger      run_trigger not null,
  git_sha      text,
  started_at   timestamptz not null default now(),
  finished_at  timestamptz,
  ok           boolean
);

create table source_run (
  id             uuid primary key default gen_random_uuid(),
  run_id         uuid not null references run(id) on delete cascade,
  source_id      text not null references source(id),
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  http_status    int,
  items_seen     int not null default 0,
  items_new      int not null default 0,
  items_matched  int not null default 0,
  error          text,
  duration_ms    int
);
create index on source_run (source_id, started_at desc);

-- ───────────────────────── documents (originals) ─────────────────────────
create table document (
  id              uuid primary key default gen_random_uuid(),
  source_id       text not null references source(id),
  external_id     text not null,                  -- stable id from the source (guid, url, procedure no.)
  url             text not null,
  title_orig      text not null,                  -- exactly as published, never translated
  lang            text,
  doc_type        doc_type not null default 'other',
  published_date  date,
  first_seen_at   timestamptz not null default now(),
  sha256          text,                           -- of the archived original
  r2_key          text,
  mime            text,
  bytes           int,
  extraction      extraction_kind not null default 'none',
  structured      jsonb,                          -- raw structured fields (EMA JSON row, feed item …)
  is_backfill     boolean not null default false,
  unique (source_id, external_id)
);
create index on document (published_date desc);

create table attachment (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid not null references document(id) on delete cascade,
  url          text not null,
  filename     text,
  sha256       text,
  r2_key       text,
  mime         text,
  bytes        int,
  extraction   extraction_kind not null default 'none',
  words        int,
  unique (document_id, url)
);

-- Full text is kept in the database only for matched documents; everything else lives gzipped in R2.
create table document_text (
  document_id    uuid references document(id) on delete cascade,
  attachment_id  uuid references attachment(id) on delete cascade,
  text           text not null,
  unique (document_id, attachment_id)
);

create table match (
  id              uuid primary key default gen_random_uuid(),
  document_id     uuid not null references document(id) on delete cascade,
  attachment_id   uuid references attachment(id) on delete cascade,
  ingredient_id   uuid references ingredient(id) on delete cascade,
  class_id        uuid references drug_class(id) on delete cascade,
  term_id         uuid references ingredient_term(id) on delete set null,
  class_term_id   uuid references class_term(id) on delete set null,
  field           match_field not null,
  start_offset    int,
  end_offset      int,
  matched_text    text not null,                  -- the words as they appear in the original
  snippet         text,
  confidence      match_conf not null default 'high',
  created_at      timestamptz not null default now(),
  check (ingredient_id is not null or class_id is not null)
);
create index on match (document_id);

-- ───────────────────────── issues & review ─────────────────────────
create table issue (
  id                  uuid primary key default gen_random_uuid(),
  doc_type            doc_type not null,
  title               text not null,              -- the anchor's original title
  anchor_document_id  uuid references document(id),
  first_date          date,
  status              issue_status not null default 'new',
  class_only          boolean not null default false,  -- matched only a class term (digest)
  is_backfill         boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index on issue (first_date desc);

create table issue_document (
  issue_id     uuid references issue(id) on delete cascade,
  document_id  uuid references document(id) on delete cascade,
  link         link_kind not null default 'copy',
  method       link_method not null default 'auto',
  score        int,
  linked_by    uuid references person(id),
  linked_at    timestamptz not null default now(),
  primary key (issue_id, document_id)
);

create table issue_ingredient (
  issue_id       uuid references issue(id) on delete cascade,
  ingredient_id  uuid references ingredient(id) on delete cascade,
  primary key (issue_id, ingredient_id)
);

-- Append-only: the review history is evidence.
create table review_event (
  id           uuid primary key default gen_random_uuid(),
  issue_id     uuid not null references issue(id) on delete cascade,
  from_status  issue_status not null,
  to_status    issue_status not null,
  comment      text,
  person_id    uuid not null references person(id),
  created_at   timestamptz not null default now(),
  check (to_status <> 'not_relevant' or length(coalesce(trim(comment), '')) > 0)
);

create function review_event_immutable() returns trigger language plpgsql as $$
begin
  raise exception 'review_event is append-only';
end $$;
create trigger review_event_no_update before update or delete on review_event
  for each row execute function review_event_immutable();

create function review_event_apply() returns trigger language plpgsql security definer
set search_path = public as $$
begin
  update issue set status = new.to_status, updated_at = now() where id = new.issue_id;
  return new;
end $$;
create trigger review_event_apply after insert on review_event
  for each row execute function review_event_apply();

-- ───────────────────────── SPC / label watch ─────────────────────────
create table spc_product (
  id             uuid primary key default gen_random_uuid(),
  ingredient_id  uuid not null references ingredient(id) on delete cascade,
  source_id      text not null references source(id),
  country_code   text not null,
  national_id    text not null,                   -- nregistro, CIS, setid, PL number …
  product_name   text not null,
  mah            text,
  url            text,
  extra          jsonb not null default '{}'::jsonb,  -- reader's discovery data (CIMA document URLs, PMDA package id …)
  active         boolean not null default true,
  unique (source_id, national_id)
);

create table spc_snapshot (
  id              uuid primary key default gen_random_uuid(),
  spc_product_id  uuid not null references spc_product(id) on delete cascade,
  fetched_at      timestamptz not null default now(),
  doc_date        date,
  sha256          text not null,
  r2_key          text,
  section_hashes  jsonb not null                  -- {"4.4": "<sha256>", "4.8": "…"}
);

create table spc_change (
  id              uuid primary key default gen_random_uuid(),
  spc_product_id  uuid not null references spc_product(id) on delete cascade,
  from_snapshot   uuid references spc_snapshot(id),
  to_snapshot     uuid not null references spc_snapshot(id),
  sections        text[] not null,
  diff            jsonb not null,                 -- [{section, before, after}] in the original language
  issue_id        uuid references issue(id),
  created_at      timestamptz not null default now()
);

-- ───────────────────────── alerts ─────────────────────────
create table subscription (
  id             uuid primary key default gen_random_uuid(),
  person_id      uuid not null references person(id) on delete cascade,
  kind           sub_kind not null,
  ingredient_id  uuid references ingredient(id) on delete cascade,  -- null = every ingredient
  created_at     timestamptz not null default now()
);

create table link_token (
  token_hash  text primary key,                   -- sha256 of the one-time code in the deep link
  person_id   uuid not null references person(id) on delete cascade,
  expires_at  timestamptz not null default now() + interval '24 hours',
  used_at     timestamptz
);

create table notification (
  id              uuid primary key default gen_random_uuid(),
  person_id       uuid references person(id) on delete set null,
  issue_id        uuid references issue(id) on delete set null,
  kind            notif_kind not null,
  dry_run         boolean not null,
  sent_at         timestamptz not null default now(),
  tg_message_id   bigint,
  error           text,
  summary         text
);

create table monthly_report (
  id            uuid primary key default gen_random_uuid(),
  month         date unique not null,             -- first day of the month reported
  xlsx_r2_key   text not null,
  xlsx_sha256   text not null,
  pdf_r2_key    text not null,
  pdf_sha256    text not null,
  generated_at  timestamptz not null default now()
);

create table app_setting (
  key    text primary key,
  value  jsonb not null
);
insert into app_setting (key, value) values
  ('telegram_dry_run', 'true'),                   -- no real message until the owner approves the first one
  ('digest_hour_cairo', '9'),
  ('backfill_months', '12');

-- ───────────────────────── audit log ─────────────────────────
create table audit_log (
  id          bigserial primary key,
  table_name  text not null,
  row_pk      text,
  action      text not null,
  old_row     jsonb,
  new_row     jsonb,
  actor       uuid,
  at          timestamptz not null default now()
);

create function audit_row() returns trigger language plpgsql security definer
set search_path = public as $$
begin
  insert into audit_log (table_name, row_pk, action, old_row, new_row, actor)
  values (tg_table_name,
          coalesce((to_jsonb(new)->>'id'), (to_jsonb(old)->>'id'), (to_jsonb(new)->>'issue_id')),
          tg_op,
          case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end,
          case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end,
          auth.uid());
  return coalesce(new, old);
end $$;

do $$
declare t text;
begin
  foreach t in array array['ingredient','ingredient_term','class_term','source','person',
                           'issue_document','issue_ingredient','subscription','app_setting','product',
                           'product_ingredient']
  loop
    execute format('create trigger audit_%1$s after insert or update or delete on %1$s
                    for each row execute function audit_row()', t);
  end loop;
end $$;

-- ───────────────────────── the simple table ─────────────────────────
create view v_issue_table with (security_invoker = true) as
select
  i.id,
  i.first_date,
  i.doc_type,
  i.title,
  i.status,
  i.class_only,
  i.is_backfill,
  ad.url                                             as link,
  ar.country_name                                    as anchor_country,
  ar.name                                            as anchor_regulator,
  (select array_agg(distinct r.country_name order by r.country_name)
     from issue_document idd
     join document d on d.id = idd.document_id
     join source s on s.id = d.source_id
     join regulator r on r.id = s.regulator_id
    where idd.issue_id = i.id)                       as countries,
  (select array_agg(distinct ing.inn_en order by ing.inn_en)
     from issue_ingredient ii join ingredient ing on ing.id = ii.ingredient_id
    where ii.issue_id = i.id)                        as ingredients,
  (select count(*) from issue_document idd where idd.issue_id = i.id) as copies
from issue i
left join document ad on ad.id = i.anchor_document_id
left join source asrc on asrc.id = ad.source_id
left join regulator ar on ar.id = asrc.regulator_id;

-- ───────────────────────── row-level security ─────────────────────────
create function my_role() returns person_role language sql stable security definer
set search_path = public as $$
  select role from person where auth_user_id = auth.uid() and active
$$;
create function my_person_id() returns uuid language sql stable security definer
set search_path = public as $$
  select id from person where auth_user_id = auth.uid() and active
$$;

do $$
declare t text;
begin
  foreach t in array array['person','ingredient','ingredient_term','drug_class','class_term',
    'ingredient_class','product','product_ingredient','regulator','source','run','source_run',
    'document','attachment','document_text','match','issue','issue_document','issue_ingredient',
    'review_event','spc_product','spc_snapshot','spc_change','subscription','link_token',
    'notification','monthly_report','app_setting','audit_log']
  loop
    execute format('alter table %I enable row level security', t);
    if t <> 'link_token' then
      execute format('create policy %1$s_read on %1$I for select to authenticated using (my_role() is not null)', t);
    end if;
  end loop;
end $$;

-- Reviewers and admins record decisions, always as themselves.
create policy review_event_write on review_event for insert to authenticated
  with check (my_role() in ('admin','reviewer') and person_id = my_person_id());

-- Reviewers and admins can merge or split copies (manual links are audited).
create policy issue_document_write on issue_document for all to authenticated
  using (my_role() in ('admin','reviewer')) with check (my_role() in ('admin','reviewer'));

-- Admins manage the watchlist, the sources, people and settings.
do $$
declare t text;
begin
  foreach t in array array['ingredient','ingredient_term','drug_class','class_term','ingredient_class',
    'product','product_ingredient','source','person','subscription','app_setting']
  loop
    execute format('create policy %1$s_admin on %1$I for all to authenticated
                    using (my_role() = ''admin'') with check (my_role() = ''admin'')', t);
  end loop;
end $$;

-- A person may subscribe or unsubscribe themselves.
create policy subscription_self on subscription for all to authenticated
  using (person_id = my_person_id()) with check (person_id = my_person_id() and kind <> 'admin_health');
