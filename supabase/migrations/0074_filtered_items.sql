-- PHAROS — what a source's filters leave out is kept, so a wrongly dropped notice can be seen (2026-11-06).
--
-- Several sources drop part of their list on purpose: keywords (a news feed keeps only safety items), categories
-- (EMA's veterinary letters, HSA's press releases). Until now a dropped item was recorded nowhere. Each run now
-- keeps the title of every item it dropped, with why (collectors/run.py, parsers/base.py dropped()); a keyword
-- filter no longer drops a notice that names a watched ingredient at all. The Sources screen shows the count
-- per source and the latest ones.

create table filtered_item (
  id            bigserial primary key,
  source_id     text not null references source(id) on delete cascade,
  title         text not null,
  reason        text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  times_seen    int not null default 1,
  unique (source_id, title)
);
create index filtered_item_source on filtered_item (source_id, last_seen_at desc);

alter table filtered_item enable row level security;
create policy filtered_item_read on filtered_item for select to authenticated using (my_role() is not null);
