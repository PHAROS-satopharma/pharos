-- PHAROS CI — clinical trials from ClinicalTrials.gov (0067): the trials of an ingredient newest update first,
-- the 90-day flags, and the serious adverse events summed across the trials with results. Runs after every
-- migration and the acceptance checks in ci.yml, on the same database: the people CI Admin (…a1) and CI Reader
-- (…b2) exist. Everything here is rolled back.
begin;

create function pg_temp.ci_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000067a001', 'CI trialamine', 'Z99ZZ67'),
  ('00000000-0000-0000-0000-00000067a002', 'CI otheramine', 'Z99ZZ68');

-- As collectors/trials.py leaves them, with days counted back from today (the flags look at the last 90 days).
-- 1: results first posted 10 days ago. 2: status changed 20 days ago, results posted two years ago.
-- 3: updated long ago, no results. 4: status changed 120 days ago (no flag). 5: the other ingredient's only.
insert into trial (nct_id, title, phase, status, previous_status, status_changed_on, start_date, completion_date,
                   sponsor, enrolment, enrolment_type, has_results, results_posted_on, last_update_on) values
  ('NCT06700001', 'Trialamine in heart failure', '{PHASE3}', 'COMPLETED', null, null, '2022-01', '2025-06-30',
   'CI Pharma', 400, 'ACTUAL', true, current_date - 10, current_date - 10),
  ('NCT06700002', 'Trialamine against placebo', '{PHASE2,PHASE3}', 'TERMINATED', 'RECRUITING', current_date - 20,
   '2021-03-01', '2024-01', 'CI University', 120, 'ACTUAL', true, current_date - 730, current_date - 20),
  ('NCT06700003', 'Trialamine pharmacokinetics', '{PHASE1}', 'COMPLETED', null, null, '2010-05', '2011-02',
   'CI Pharma', 24, 'ACTUAL', false, null, '2012-03-01'),
  ('NCT06700004', 'Trialamine in children', '{NA}', 'RECRUITING', 'NOT_YET_RECRUITING', current_date - 120,
   '2025-01', '2028-12', 'CI Hospital', 60, 'ESTIMATED', false, null, current_date - 120),
  ('NCT06700005', 'Otheramine only', '{PHASE4}', 'RECRUITING', null, null, '2026-01', null,
   'CI Pharma', 10, 'ESTIMATED', true, current_date - 5, current_date - 1);
insert into trial_ingredient (ingredient_id, nct_id) values
  ('00000000-0000-0000-0000-00000067a001', 'NCT06700001'),
  ('00000000-0000-0000-0000-00000067a001', 'NCT06700002'),
  ('00000000-0000-0000-0000-00000067a001', 'NCT06700003'),
  ('00000000-0000-0000-0000-00000067a001', 'NCT06700004'),
  ('00000000-0000-0000-0000-00000067a002', 'NCT06700005');
insert into trial_search (ingredient_id, names, trials, searched_at) values
  ('00000000-0000-0000-0000-00000067a001', '{CI trialamine,Trialix}', 4, '2026-11-02 01:10+00');

-- Stroke twice, in the sponsors' own capitals: one term across two trials. An other (non-serious) event and a
-- serious event nobody had are not among the serious events; the other ingredient's trial is never counted.
insert into trial_event (nct_id, serious, term, organ_system, affected, at_risk, groups) values
  ('NCT06700001', true,  'Stroke', 'Nervous system disorders', 3, 400,
   '[{"group":"Trialamine","affected":2,"at_risk":200},{"group":"Placebo","affected":1,"at_risk":200}]'),
  ('NCT06700002', true,  'STROKE', 'Nervous system disorders', 2, 120, '[]'),
  ('NCT06700001', true,  'Cardiac failure', 'Cardiac disorders', 4, 400, '[]'),
  ('NCT06700001', false, 'Headache', 'Nervous system disorders', 40, 400, '[]'),
  ('NCT06700002', true,  'Pancreatitis', 'Gastrointestinal disorders', 0, 120, '[]'),
  ('NCT06700005', true,  'Stroke', 'Nervous system disorders', 9, 10, '[]');

-- Read as CI Reader; the temp table that keeps the answer is made by the owner.
create temp table r (j jsonb);
grant select, insert on r to authenticated;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
insert into r select ingredient_trials('00000000-0000-0000-0000-00000067a001');
select pg_temp.ci_assert((select array_agg(x ->> 'nct_id' order by n) from r, jsonb_array_elements(j -> 'trials')
                           with ordinality as a(x, n)) = '{NCT06700001,NCT06700002,NCT06700004,NCT06700003}',
                         'the trials of the ingredient only, newest update first');
select pg_temp.ci_assert((select (x ->> 'new_results')::boolean and not (x ->> 'status_changed')::boolean
                            from r, jsonb_array_elements(j -> 'trials') x where x ->> 'nct_id' = 'NCT06700001'),
                         'results first posted 10 days ago are new results');
select pg_temp.ci_assert((select (x ->> 'status_changed')::boolean and not (x ->> 'new_results')::boolean
                                 and x ->> 'previous_status' = 'RECRUITING'
                            from r, jsonb_array_elements(j -> 'trials') x where x ->> 'nct_id' = 'NCT06700002'),
                         'a status changed 20 days ago is flagged, with the status before it');
select pg_temp.ci_assert((select not (x ->> 'status_changed')::boolean
                            from r, jsonb_array_elements(j -> 'trials') x where x ->> 'nct_id' = 'NCT06700004'),
                         'a status changed 120 days ago is not flagged');
select pg_temp.ci_assert((select (j ->> 'recent')::int = 2 and (j ->> 'with_results')::int = 2 from r),
                         'two trials changed in 90 days, two have results');
select pg_temp.ci_assert((select j -> 'searched' ->> 'trials' = '4' and j -> 'searched' -> 'names' ? 'Trialix' from r),
                         'the screen says when and under which names the ingredient was searched');
select pg_temp.ci_assert((select array_agg(lower(x ->> 'term') order by n) from r,
                           jsonb_array_elements(j -> 'events') with ordinality as a(x, n)) = '{stroke,"cardiac failure"}',
                         'serious events only, a term nobody had left out, most affected first');
select pg_temp.ci_assert((select (x ->> 'affected')::int = 5 and (x ->> 'trials')::int = 2
                                 and (x ->> 'at_risk')::int = 520
                            from r, jsonb_array_elements(j -> 'events') x where lower(x ->> 'term') = 'stroke'),
                         'one term in two spellings is summed across the trials, never the other ingredient''s');
select pg_temp.ci_assert(pg_temp.refused($$insert into trial (nct_id, title, status)
  values ('NCT06799999', 'Mine', 'RECRUITING')$$) like '42501%', 'nobody in the app writes a trial');
select pg_temp.ci_assert(pg_temp.refused($$insert into trial_event (nct_id, serious, term, affected)
  values ('NCT06700003', true, 'Invented', 1)$$) like '42501%', 'nobody in the app writes an adverse event');
select pg_temp.ci_assert((select count(*) from trial_event where nct_id = 'NCT06700001') = 3,
                         'a member of the team reads the events');
reset role;

-- A signed-in account that is not a member of the team, and anyone signed out, read nothing.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000067ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ci_assert(pg_temp.refused($$select ingredient_trials('00000000-0000-0000-0000-00000067a001')$$)
                         like '42501%', 'an account that is not a member of the team is refused');
select pg_temp.ci_assert((select count(*) from trial) = 0, 'and sees no trial');
reset role;
set role anon;
select pg_temp.ci_assert(pg_temp.refused($$select ingredient_trials('00000000-0000-0000-0000-00000067a001')$$)
                         like '42501%', 'nobody signed out reads the trials');
reset role;

select pg_temp.ci_assert((select prosecdef from pg_proc where proname = 'ingredient_trials'),
                         'the trials are read as their owner, after one role check');

rollback;
