-- PHAROS — levofloxacin's words are looked for in the stored notices after all (2026-11-06).
--
-- 0034 marked as done the words of every ingredient created before the last run recorded as a backfill.
-- Every collection run was recorded as a backfill (collectors/run.py, fixed in the same change), so the
-- scheduled 12h run of 5 Nov 2026 22:53 UTC counted as one, and levofloxacin (added 21:36 UTC, after the
-- last backfill run of 20:28 UTC) was marked as already checked: its 47 words were never looked for in what
-- PHAROS already held. They are due again, so the next check of the past (collectors/rematch.py) looks for
-- them in the stored notices of the last 12 months; what it finds is history (no Telegram message).
-- Lornoxicam (added 4 Nov, before the first backfill) and the NSAID class words stay done.
update ingredient_term t
   set rematched_at = null
  from ingredient i
 where i.id = t.ingredient_id
   and i.created_at > timestamptz '2026-11-05 20:28:12+00'
   and t.rematched_at is not null
   and not exists (select 1 from rematch_job j
                    where j.finished_at is not null and t.id = any (j.ingredient_term_ids));
