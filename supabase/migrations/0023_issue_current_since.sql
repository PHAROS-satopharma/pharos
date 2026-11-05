-- PHAROS — when a history issue became current (audit follow-up, 2026-11-05).
--
-- A fresh anchor or a fresh national copy takes a history issue out of the history (0001 is_backfill).
-- The class-wide digest picked issues by created_at only, so a class-only issue revived that way was
-- older than the last digest and never reached anyone. current_since records the moment it became
-- current (null: current from the start, or still history); the digest reads created_at or this.

alter table issue add column if not exists current_since timestamptz;
