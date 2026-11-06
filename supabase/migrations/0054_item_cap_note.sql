-- PHAROS — a run cut by the item cap is a note, not a failure (2026-11-06).
--
-- A source run stores at most max_new_items new items. The rest used to be dropped without a word, and the run
-- still counted as complete, so NCBI literature (which reads from the last complete run) moved its window past
-- the papers it never read: after an NCBI outage, the papers over the 800 cap were lost for good. The
-- collectors now write "item cap reached: N new item(s) wait for the next run" and leave last_ok_at alone
-- (collectors/run.py). Like "time budget reached: …" it is a note on a run that read its source, so
-- source_run_failed() lists it; web/src/features/sources/queries.ts (RUN_NOTE) keeps the same list.
-- Same signature; create or replace keeps the grants.

create or replace function source_run_failed(p_error text) returns boolean
language sql immutable set search_path = public as $$
  select p_error is not null
     and p_error !~ '^(imap not configured|imap: |[0-9]+ item\(s\) failed; first: |time budget reached: |item cap reached: |[0-9]+ error\(s\); first: |[0-9]+ product\(s\) without label text)'
$$;
