-- PHAROS — an old notice found by a regular run is history (launch check, 2026-11-05).
--
-- Until the collector fix "Treat an old notice found by a regular run as history" (5 Nov 2026, 10:12 Cairo),
-- a regular run marked a notice as history only on a source's first read. Denmark's list holds every
-- letter it ever sent, so the first scheduled collection (5 Nov, 08:46 Cairo) stored two letters from
-- 2015 and 2016 (Tarceva, Nicorandil) as current, and they went out in the class-wide digest. The
-- collector now applies the rule below to every new notice; this applies it to the ones stored before:
-- a notice published more than alert_max_age_days (default 60) before PHAROS first saw it is history,
-- and so is a notification whose anchor notice is. Notices with no published date are left as they are.
-- Running it again changes nothing. The audit trigger records every changed row.

with max_age as (
  select coalesce((select (value #>> '{}')::int from app_setting where key = 'alert_max_age_days'), 60) as days
), old as (
  update document d
     set is_backfill = true
    from max_age m
   where false and not d.is_backfill  -- TEMPORARY break
     and d.published_date is not null
     and d.published_date < (d.first_seen_at at time zone 'Africa/Cairo')::date - m.days
  returning d.id
)
update issue i
   set is_backfill = true
  from old
 where i.anchor_document_id = old.id
   and not i.is_backfill;
