-- PHAROS — the weekly list check (collectors/completeness.py, audit.yml), 2026-11-07.
--
-- Per notice source, one row a week: its own list read whole (as a backfill reads it, nothing stored), set
-- against what PHAROS holds. listed = notices on the source's list; stored = held by PHAROS; older = published
-- before the kept history (app_setting backfill_months), not stored on purpose; missing = listed, inside the
-- kept history and not stored, the newest named in missing_items for an admin; filtered = what the source's
-- filters left out (kept in filtered_item, 0074). complete is false when part of the list could not be read,
-- and error says why. The Sources screen shows the latest row. Until now this was checked by hand.

create table list_check (
  id             bigserial primary key,
  checked_at     timestamptz not null default now(),
  source_id      text not null references source(id) on delete cascade,
  listed         int not null default 0,
  stored         int not null default 0,
  older          int not null default 0,
  missing        int not null default 0,
  filtered       int not null default 0,
  missing_items  jsonb not null default '[]'::jsonb,     -- [{external_id, title, url, published}]
  complete       boolean not null default true,
  error          text
);
create index list_check_latest on list_check (source_id, checked_at desc);

alter table list_check enable row level security;
create policy list_check_read on list_check for select to authenticated using (my_role() is not null);
