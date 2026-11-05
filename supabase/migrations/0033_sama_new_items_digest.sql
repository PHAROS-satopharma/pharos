-- PHAROS — Dr Sama receives the daily message of new items on the authorities' pages (2026-11-06).
--
-- Decided with her review: new items are shown on the Sources screen and in one Telegram message a day,
-- switched on for her. She can switch it off herself on the People screen ("New items on the authorities'
-- pages, once a day"). Guarded by her address: on any other database (CI) this inserts nothing, and it
-- never adds a second subscription.

insert into subscription (person_id, kind)
select p.id, 'new_items_digest'
  from person p
 where lower(p.email) = 'sama.mosaad@satopharma.com'
   and not exists (select 1 from subscription s where s.person_id = p.id and s.kind = 'new_items_digest');
