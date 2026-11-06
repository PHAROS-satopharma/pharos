-- PHAROS CI — signal steps inside the finding (0042): Concerns us opens a signal once, Doesn't concern us closes
-- it as not validated while nothing real was done, finding_state() carries the signal, and the step functions
-- keep their guards. Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3)
-- exist. Everything here happens in one transaction that is rolled back at the end (review_event and
-- signal_event cannot be deleted).
-- One transaction means one now(): every signal_event shares its created_at, so the step lists below put
-- 'opened' first by name instead of trusting the clock.

begin;

create function pg_temp.sf_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.sf_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

select signal_cairo_today() as today \gset
select id as reviewer_id from person where auth_user_id = '00000000-0000-0000-0000-0000000000c3' \gset

-- ───────────── two ingredients, four notices ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000042a001', 'CI signaline', 'Z97ZZ02'),
  ('00000000-0000-0000-0000-00000042a002', 'CI secondine', 'Z97ZZ03');
insert into issue (id, doc_type, title) values
  ('00000000-0000-0000-0000-00000042e001', 'dhpc', 'CI signaline: a new warning'),
  ('00000000-0000-0000-0000-00000042e002', 'dhpc', 'CI signaline: a second warning'),
  ('00000000-0000-0000-0000-00000042e003', 'dhpc', 'CI signaline and CI secondine together'),
  ('00000000-0000-0000-0000-00000042e004', 'dhpc', 'CI signaline: with the switch off');
insert into issue_ingredient (issue_id, ingredient_id) values
  ('00000000-0000-0000-0000-00000042e001', '00000000-0000-0000-0000-00000042a001'),
  ('00000000-0000-0000-0000-00000042e002', '00000000-0000-0000-0000-00000042a001'),
  ('00000000-0000-0000-0000-00000042e003', '00000000-0000-0000-0000-00000042a001'),
  ('00000000-0000-0000-0000-00000042e003', '00000000-0000-0000-0000-00000042a002'),
  ('00000000-0000-0000-0000-00000042e004', '00000000-0000-0000-0000-00000042a001');

-- ───────────── the setting ─────────────
select pg_temp.sf_assert((select value from app_setting where key = 'signal_auto_open') = 'true'::jsonb,
  'Concerns us opens a signal by default (signal_auto_open)');

-- ───────────── no decision: the finding carries no signal ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select finding_state(array['00000000-0000-0000-0000-00000042e001']::uuid[])::text as sf_none \gset
reset role;
select pg_temp.sf_assert(:'sf_none'::jsonb -> '00000000-0000-0000-0000-00000042e001' -> 'signal' = 'null'::jsonb,
  'a notice nobody decided has no signal in finding_state');

-- ───────────── Concerns us opens a signal, once ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e001', 'new', 'relevant', 'Our tablets carry it', my_person_id());
reset role;
select s.id as sig1 from signal s join signal_issue si on si.signal_id = s.id
 where si.issue_id = '00000000-0000-0000-0000-00000042e001' \gset
select pg_temp.sf_assert((select count(*) from signal_issue where issue_id = '00000000-0000-0000-0000-00000042e001') = 1,
  'Concerns us opens one signal for the notice');
select pg_temp.sf_assert((select ref ~ '^SIG-\d{4}-\d{3}$' and title = 'CI signaline: a new warning'
                                 and ingredient_id = '00000000-0000-0000-0000-00000042a001'
                                 and stage = 'validation' and opened_by = :'reviewer_id'
                                 and validation_due = :'today'::date + signal_due_days('validation')
                            from signal where id = :'sig1'),
  'the signal is numbered, named after the notice, for its ingredient, opened by the person who decided, due for validation');
select pg_temp.sf_assert((select array_agg(step::text order by created_at, id) from signal_event where signal_id = :'sig1')
    = array['opened']
    and (select issue_id = '00000000-0000-0000-0000-00000042e001' and person_id = :'reviewer_id'
           from signal_event where signal_id = :'sig1'),
  'the opening is one step, recorded for the notice by the person who decided');

-- ───────────── finding_state carries the signal ─────────────
set role authenticated;
select finding_state(array['00000000-0000-0000-0000-00000042e001']::uuid[])
         -> '00000000-0000-0000-0000-00000042e001' -> 'signal' as sf_sig \gset
reset role;
select pg_temp.sf_assert(:'sf_sig'::jsonb ->> 'id' = :'sig1'::text
    and :'sf_sig'::jsonb ->> 'ref' ~ '^SIG-\d{4}-\d{3}$'
    and :'sf_sig'::jsonb ->> 'stage' = 'validation'
    and :'sf_sig'::jsonb ->> 'next_step' = 'validated'
    and (:'sf_sig'::jsonb ->> 'next_due')::date = :'today'::date + signal_due_days('validation')
    and (:'sf_sig'::jsonb ->> 'overdue')::boolean = false
    and :'sf_sig'::jsonb -> 'priority' = 'null'::jsonb
    and :'sf_sig'::jsonb -> 'outcome' = 'null'::jsonb
    and :'sf_sig'::jsonb -> 'owner' = 'null'::jsonb
    and :'sf_sig'::jsonb ->> 'opened_by' = 'CI Reviewer',
  'finding_state carries the signal: its reference, stage, next step, next due day, not overdue');
select pg_temp.sf_assert(jsonb_array_length(:'sf_sig'::jsonb -> 'steps') = 1
    and :'sf_sig'::jsonb -> 'steps' -> 0 ->> 'step' = 'opened'
    and :'sf_sig'::jsonb -> 'steps' -> 0 ->> 'to_stage' = 'validation'
    and :'sf_sig'::jsonb -> 'steps' -> 0 ->> 'person' = 'CI Reviewer'
    and (:'sf_sig'::jsonb -> 'steps' -> 0 ->> 'at') is not null,
  'the steps are listed with who took them and when');

-- ───────────── a reader cannot take a step; a stale stage is refused ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.sf_refused(format($q$select signal_take_step(%L, 'validated', 'validation', 'Plausible', 'high')$q$, :'sig1'))
  as sf_reader \gset
select pg_temp.sf_refused(format($q$select open_signal_as(%L, 'By hand', null, %L)$q$,
  '00000000-0000-0000-0000-00000042e002', :'reviewer_id')) as sf_as_reader \gset
reset role;
select pg_temp.sf_assert(:'sf_reader' like '42501%', 'a reader cannot take a step');
select pg_temp.sf_assert(:'sf_as_reader' like '42501%', 'open_signal_as is the trigger''s alone: no signed-in person may call it');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.sf_refused(format($q$select open_signal_as(%L, 'By hand', null, %L)$q$,
  '00000000-0000-0000-0000-00000042e002', :'reviewer_id')) as sf_as_reviewer \gset
select pg_temp.sf_refused(format($q$select signal_take_step(%L, 'validated', 'assessment', 'Plausible', 'high')$q$, :'sig1'))
  as sf_stale \gset
reset role;
select pg_temp.sf_assert(:'sf_as_reviewer' like '42501%', 'nor may a reviewer call open_signal_as directly');
select pg_temp.sf_assert(:'sf_stale' like 'PH409 STALE_SIGNAL%', 'a step from a stage the signal is not at is refused as stale (PH409)');
select pg_temp.sf_assert((select stage from signal where id = :'sig1') = 'validation', 'the refused steps changed nothing');

-- ───────────── Doesn't concern us while nothing real was done: closed as not validated ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e001', 'relevant', 'not_relevant', 'Not our salt', my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000042e001']::uuid[])
         -> '00000000-0000-0000-0000-00000042e001' -> 'signal' as sf_closed \gset
reset role;
select pg_temp.sf_assert((select stage = 'closed' and outcome = 'not_validated' and closed_at is not null
                            from signal where id = :'sig1'),
  'Doesn''t concern us closes a signal still in validation as not validated');
select pg_temp.sf_assert((select array_agg(step::text order by step <> 'opened', created_at, id) from signal_event where signal_id = :'sig1')
    = array['opened', 'not_validated']
    and (select comment = 'Decision changed: Not our salt' and person_id = :'reviewer_id'
                and from_stage = 'validation' and to_stage = 'closed' and outcome = 'not_validated'
           from signal_event where signal_id = :'sig1' and step = 'not_validated'),
  'the closing step says the decision changed, with her reason, by the person who decided');
select pg_temp.sf_assert(:'sf_closed'::jsonb ->> 'stage' = 'closed'
    and :'sf_closed'::jsonb ->> 'outcome' = 'not_validated'
    and :'sf_closed'::jsonb -> 'next_step' = 'null'::jsonb
    and :'sf_closed'::jsonb -> 'next_due' = 'null'::jsonb
    and jsonb_array_length(:'sf_closed'::jsonb -> 'steps') = 2,
  'finding_state shows the closed signal with no next step');

-- ───────────── Concerns us again: never a second signal ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e001', 'not_relevant', 'relevant', 'It is our salt after all', my_person_id());
reset role;
select pg_temp.sf_assert((select count(*) from signal_issue where issue_id = '00000000-0000-0000-0000-00000042e001') = 1
    and (select count(*) from signal_event where signal_id = :'sig1') = 2
    and (select stage from signal where id = :'sig1') = 'closed',
  'Concerns us again opens no second signal and reopens nothing by itself');

-- ───────────── a signal already validated is left alone by Doesn't concern us ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e002', 'new', 'relevant', null, my_person_id());
select s.id as sig2 from signal s join signal_issue si on si.signal_id = s.id
 where si.issue_id = '00000000-0000-0000-0000-00000042e002' \gset
select signal_take_step(:'sig2', 'validated', 'validation', 'Plausible mechanism', 'high') as sf_st \gset
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e002', 'relevant', 'not_relevant', 'Changed my mind', my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000042e002']::uuid[])
         -> '00000000-0000-0000-0000-00000042e002' -> 'signal' as sf_kept \gset
reset role;
select pg_temp.sf_assert(:'sf_st' = 'assessment' and (select stage = 'assessment' and priority = 'high' from signal where id = :'sig2'),
  'a reviewer validates the auto-opened signal through signal_take_step as before');
select pg_temp.sf_assert((select array_agg(step::text order by step <> 'opened', created_at, id) from signal_event where signal_id = :'sig2')
    = array['opened', 'validated'],
  'Doesn''t concern us leaves a signal that was validated as it is');
select pg_temp.sf_assert(:'sf_kept'::jsonb ->> 'stage' = 'assessment'
    and :'sf_kept'::jsonb ->> 'priority' = 'high'
    and :'sf_kept'::jsonb ->> 'next_step' = 'assessed'
    and (:'sf_kept'::jsonb ->> 'next_due')::date = :'today'::date + signal_due_days('assessment', 'high'),
  'finding_state shows the validated signal with its assessment due day');

-- ───────────── a notice of two ingredients opens a signal with no ingredient ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e003', 'new', 'relevant', null, my_person_id());
reset role;
select pg_temp.sf_assert((select s.ingredient_id is null and s.title = 'CI signaline and CI secondine together'
                            from signal s join signal_issue si on si.signal_id = s.id
                           where si.issue_id = '00000000-0000-0000-0000-00000042e003'),
  'a notice of two ingredients opens a signal with no ingredient');

-- ───────────── the switch ─────────────
update app_setting set value = 'false'::jsonb where key = 'signal_auto_open';
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000042e004', 'new', 'relevant', null, my_person_id());
reset role;
update app_setting set value = 'true'::jsonb where key = 'signal_auto_open';
select pg_temp.sf_assert(not exists (select 1 from signal_issue where issue_id = '00000000-0000-0000-0000-00000042e004'),
  'with signal_auto_open false, Concerns us opens nothing');

-- ───────────── the trigger sorts after review_event_apply ─────────────
select pg_temp.sf_assert((select tgname from pg_trigger where tgrelid = 'review_event'::regclass and tgname like '%open_signal%')
    > 'review_event_apply',
  'the trigger that opens the signal fires after the one that sets the notice''s status');

select set_config('request.jwt.claims', '', false);
rollback;
