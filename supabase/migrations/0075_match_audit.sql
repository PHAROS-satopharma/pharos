-- PHAROS — the weekly matching audit (collectors/match_audit.py, audit.yml), 2026-11-06.
--
-- Per watched ingredient, one row a week: how many stored notices name it (its INN in every language, salts,
-- brands, codes), how many of those were not linked to it and were linked now as history, the ones that could
-- not be linked (for an admin), and the English names RxNorm gives only to another substance ("Ofloxacin" on
-- levofloxacin). The Ingredients screen shows the latest row; nothing here removes a name.

create table match_audit (
  id              bigserial primary key,
  checked_at      timestamptz not null default now(),
  ingredient_id   uuid not null references ingredient(id) on delete cascade,
  names_checked   int not null default 0,
  notices_named   int not null default 0,
  unlinked_found  int not null default 0,
  linked_now      int not null default 0,
  left_over       jsonb not null default '[]'::jsonb,     -- [{document_id, title}]
  flagged_names   jsonb not null default '[]'::jsonb,     -- [{term_id, term, why}]
  unchecked_names int not null default 0                  -- names RxNorm could not be asked about this week
);
create index match_audit_latest on match_audit (ingredient_id, checked_at desc);

alter table match_audit enable row level security;
create policy match_audit_read on match_audit for select to authenticated using (my_role() is not null);
