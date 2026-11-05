-- PHAROS — a source's "last published" date is never in the future (launch check, 2026-11-05).
--
-- The shared date reader took gov.uk's Atom timestamps ("2026-10-12T11:00:23+01:00") day-first, so the
-- UK alerts source recorded 10 Dec 2026 as its newest item. The notices themselves were stored with the
-- right dates (they are dated from the gov.uk content API); only source.last_item_at was wrong, and it
-- moves only forward (greatest()), so it would have stayed in the future. The reader is fixed in the
-- collector; this resets any future value to the newest stored notice of that source, or to nothing.

update source s
   set last_item_at = (select max(d.published_date)::timestamp at time zone 'UTC'
                         from document d
                        where d.source_id = s.id
                          and d.published_date <= current_date)
 where s.last_item_at > now() + interval '1 day';
