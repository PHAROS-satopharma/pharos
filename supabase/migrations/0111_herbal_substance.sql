-- 0111 — EMA's herbal substances kept in PHAROS (11 November 2026).
--
-- Dr Sama could not add "ivy leaves" on the Ingredients screen. The lookup read EMA's HMPC herbal list
-- (medicines-output-herbal_medicines-report-output-json_en.json) from EMA's website at the moment someone typed,
-- and EMA's site now answers that file with "429 Too Many Requests": no herbal substance could be found, so no
-- herbal could be added. The list is now loaded once a day by the collection on GitHub (collectors/herbal.py,
-- the "Herbal list" step of PHAROS collect), and the lookup reads it from here.
--
-- One row per herbal substance, as EMA writes it: the English common name ("Ivy leaf"), the Latin name
-- ("Hederae helicis folium") and the plant with its author ("Hedera helix L."; several are separated by ";").
-- Ivy leaf is written here now, so it can be added before the first daily load.

create table herbal_substance (
  name       text primary key,
  latin      text not null,
  botanical  text not null default '',
  loaded_at  timestamptz not null default now()
);

alter table herbal_substance enable row level security;
create policy herbal_substance_read on herbal_substance for select to authenticated using (my_role() is not null);

insert into herbal_substance (name, latin, botanical)
values ('Ivy leaf', 'Hederae helicis folium', 'Hedera helix L.');
