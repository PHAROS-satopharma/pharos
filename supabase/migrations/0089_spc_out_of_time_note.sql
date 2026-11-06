-- PHAROS — a label-watch run that only ran out of time is a note, not a failure (2026-11-06).
--
-- The label watch (collectors/spc/run.py) reads labels in turn until its share of the run's time is spent, and
-- writes "out of time: N label(s) left for the next run" when the time ran out. When that was the only note, the
-- run's error started with "out of time: " and source_run_failed() read it as a failed run: the Sources screen
-- showed the week's paracetamol run as Failed when it had read hundreds of labels. Like "time budget reached: "
-- it is a note on a run that read its source; web/src/features/sources/queries.ts (RUN_NOTE) keeps the same list.
-- Same signature; create or replace keeps the grants.

create or replace function source_run_failed(p_error text) returns boolean
language sql immutable set search_path = public as $$
  select p_error is not null
     and p_error !~ '^(imap not configured|imap: |[0-9]+ item\(s\) failed; first: |time budget reached: |item cap reached: |[0-9]+ error\(s\); first: |[0-9]+ product\(s\) without label text|out of time: )'
$$;
