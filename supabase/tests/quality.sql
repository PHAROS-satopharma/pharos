-- PHAROS CI — Quality (0107): deviations (PV-SOP-021), audits (PV-SOP-022) and the one CAPA plan both feed.
-- Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.
-- Everything here happens in one transaction that is rolled back at the end (quality_event and audit_log rows
-- cannot be deleted).

begin;

create function pg_temp.q_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.q_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

create function pg_temp.q_as(p uuid) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object('sub', p, 'role', 'authenticated')::text, false)
$$;

select signal_cairo_today() as today \gset
select extract(year from signal_cairo_today())::int as yr \gset
select (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000c3') as reviewer_id \gset

-- ───────────── deviations: D001/<year>, D002/<year>; the serial restarts with the year ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_open('Late case entry', 'A serious case was entered on day 16 instead of day 15.',
                      (:'today'::date - 3), (:'today'::date - 1), true, true, false) as d1 \gset
select deviation_open('Wrong SOP version', 'Form PV-FM-004 version 2 was used after version 3 was issued.',
                      null, :'today'::date) as d2 \gset
select pg_temp.q_refused($q$select deviation_open('', 'x', null, signal_cairo_today())$q$) as d_no_title \gset
select pg_temp.q_refused($q$select deviation_open('Future', 'x', null, signal_cairo_today() + 1)$q$) as d_future \gset
reset role;
select ref as d1_ref from deviation where id = :'d1' \gset
select ref as d2_ref from deviation where id = :'d2' \gset
-- The next year (recorded on 2 January) starts again at D001.
select deviation_open_as(:'reviewer_id', make_date(:yr + 1, 1, 2), 'New year', 'The first of the year.',
                         null, make_date(:yr + 1, 1, 2)) as d3 \gset
select ref as d3_ref from deviation where id = :'d3' \gset
select pg_temp.q_assert(:'d1_ref' = 'D001/' || :yr and :'d2_ref' = 'D002/' || :yr,
  'deviations are numbered D001/' || :yr || ' then D002/' || :yr);
select pg_temp.q_assert(:'d3_ref' = 'D001/' || (:yr + 1), 'the serial restarts each year: D001/' || (:yr + 1));
select pg_temp.q_assert(:'d_no_title' like '22023%' and :'d_future' like '22023%',
  'a deviation needs a title, and the day it was detected has passed');
select pg_temp.q_assert(
  (select status = 'open' and level is null and patient_safety and regulatory_compliance and not document_quality
     from deviation where id = :'d1'),
  'a new deviation is open, with no level until QA sets it, and its impact flags');

-- ───────────── a reader reads everything and is refused every write ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select pg_temp.q_refused($q$select deviation_open('R', 'R', null, signal_cairo_today())$q$) as r1 \gset
select pg_temp.q_refused(format('select deviation_update(%L, %L, %L)', :'d1', 'open', '{"root_cause":"x"}')) as r2 \gset
select pg_temp.q_refused(format('select deviation_set_level(%L, %L, 2, %L)', :'d1', 'open', 'why')) as r3 \gset
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L)', :'d1', 'investigating', 'open')) as r4 \gset
select pg_temp.q_refused($q$select audit_open('internal', 'R', 'QA')$q$) as r5 \gset
select pg_temp.q_refused(format('select capa_open(%L, null, %L, null)', :'d1', 'fix')) as r6 \gset
select pg_temp.q_refused($q$insert into deviation (year, serial, title, description, detected_on, created_by)
  values (2026, 900, 'x', 'x', '2026-01-01', my_person_id())$q$) as r7 \gset
select pg_temp.q_refused(format('update deviation set status = %L where id = %L', 'closed', :'d1')) as r8 \gset
select pg_temp.q_refused(format('delete from deviation where id = %L', :'d1')) as r9 \gset
select count(*) as reader_sees from deviation where id in (:'d1', :'d2') \gset
select jsonb_array_length(quality_state() -> 'deviations') as reader_state \gset
reset role;
select pg_temp.q_assert(:'r1' like '42501%' and :'r2' like '42501%' and :'r3' like '42501%' and :'r4' like '42501%'
    and :'r5' like '42501%' and :'r6' like '42501%',
  'a reader is refused every write function');
select pg_temp.q_assert(:'r7' like '42501%' and :'r8' like '42501%' and :'r9' like '42501%',
  'nobody writes the tables directly, not even to delete');
select pg_temp.q_assert(:reader_sees = 2 and :reader_state >= 2, 'a reader reads the deviations and the Quality state');

-- ───────────── the deviation's steps; stale writes are refused ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_step(:'d1', 'investigating', 'open') as s1 \gset
-- someone who still sees it open
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L)', :'d1', 'investigating', 'open')) as stale1 \gset
select pg_temp.q_refused(format('select deviation_update(%L, %L, %L)', :'d1', 'open', '{"root_cause":"x"}')) as stale2 \gset
select pg_temp.q_refused(format('select deviation_set_level(%L, %L, 2, null)', :'d1', 'investigating')) as no_comment \gset
select deviation_set_level(:'d1', 'investigating', 2, 'May affect compliance: the 15-day timeline.') as s2 \gset
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L)', :'d1', 'capa', 'investigating')) as no_root \gset
select deviation_update(:'d1', 'investigating', jsonb_build_object(
  'inv_cause', 'The case was misread as non-serious.', 'inv_people_time', 'The PV officer, 3 to 4 Nov, one day.',
  'inv_reoccur', 'Yes', 'inv_similar', 'No', 'inv_other_impact', 'None', 'inv_training', 'Trained on PV-SOP-006',
  'root_cause', 'Seriousness criteria not checked at intake.')) as s3 \gset
select deviation_step(:'d1', 'capa', 'investigating') as s4 \gset
-- no CAPA yet: the QA Manager cannot approve
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L, %L, true)', :'d1', 'approved', 'capa', 'ok')) as no_capa \gset
reset role;
select pg_temp.q_assert(:'s1' = 'investigating' and :'s2' = 'investigating' and :'s4' = 'capa',
  'open → investigating → capa');
select pg_temp.q_assert(:'stale1' like 'PH409%STALE_QUALITY%' and :'stale2' like 'PH409%STALE_QUALITY%',
  'a step or a change from a status that moved meanwhile is refused with PH409');
select pg_temp.q_assert(:'no_comment' like '22023%comment%', 'QA sets the level with a comment');
select pg_temp.q_assert(:'no_root' like '22023%root cause%', 'no CAPA step before the root cause');
select pg_temp.q_assert(:'no_capa' like '22023%CAPA%', 'no approval before its CAPA');

-- ───────────── a CAPA needs exactly one source ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select audit_open('external', 'Partner audit 2026', 'Partner Pharma (MAH)', 'Dr Lead', null,
                  (:'today'::date - 14), (:'today'::date - 13), (:'today'::date - 11)) as a1 \gset
select audit_add_observation(:'a1', 'Case processing timelines not monitored.', 'major', :'reviewer_id') as o1 \gset
select audit_add_observation(:'a1', 'Training records incomplete.', 'minor') as o2 \gset
select pg_temp.q_refused(format('select capa_open(%L, %L, %L, null)', :'d1', :'o1', 'Both')) as both_src \gset
select pg_temp.q_refused($q$select capa_open(null, null, 'None', null)$q$) as no_src \gset
select pg_temp.q_refused(format('select capa_open(%L, null, null, null)', :'d1')) as no_action \gset
select capa_open(:'d1', null, 'Re-assess the case.', 'Add a seriousness checklist at intake.', :'reviewer_id', null,
                 (:'today'::date + 2)) as c1 \gset
select capa_open(null, :'o1', 'Weekly timeline report.', null, null, 'Head of Regulatory Affairs',
                 (:'today'::date + 30)) as c2 \gset
reset role;
select pg_temp.q_refused(format(
  'insert into capa (year, serial, deviation_id, observation_id, corrective_action, created_by) values (%s, 998, %L, %L, %L, %L)',
  :yr, :'d1', :'o1', 'x', :'reviewer_id')) as both_direct \gset
select ref as c1_ref from capa where id = :'c1' \gset
select ref as c2_ref from capa where id = :'c2' \gset
select number as o2_number from audit_observation where id = :'o2' \gset
select pg_temp.q_assert(:'both_src' like '22023%exactly one%' and :'no_src' like '22023%exactly one%'
    and :'both_direct' like '23514%capa_one_source%',
  'a CAPA comes from exactly one deviation or one audit observation, in the function and in the table');
select pg_temp.q_assert(:'no_action' like '22023%', 'a CAPA needs a corrective or a preventive action');
select pg_temp.q_assert(:'c1_ref' = 'CAPA-001/' || :yr and :'c2_ref' = 'CAPA-002/' || :yr and :o2_number = 2,
  'CAPAs are numbered CAPA-001/' || :yr || ', and observations within their audit');

-- ───────────── a deviation cannot close while a CAPA is open ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_step(:'d1', 'approved', 'capa', 'Not enough: interview the officer.', false) as back \gset
select deviation_step(:'d1', 'capa', 'investigating') as again \gset
select deviation_step(:'d1', 'approved', 'capa', 'Investigation satisfactory.', true) as appr \gset
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L, %L)', :'d1', 'closed', 'approved', 'Done')) as close_open_capa \gset
select capa_step(:'c1', 'approved', 'draft', 'Approved by QA.') as c1a \gset
select capa_step(:'c1', 'in_progress', 'approved') as c1b \gset
select pg_temp.q_refused(format('select capa_step(%L, %L, %L)', :'c1', 'done', 'in_progress')) as no_evidence \gset
select capa_step(:'c1', 'done', 'in_progress', null, :'today'::date, 'Checklist v1 issued, DOC-PV-112.') as c1c \gset
select capa_step(:'c1', 'not_effective', 'done', 'A late case again on 8 Nov.') as c1d \gset
select capa_step(:'c1', 'done', 'in_progress', null, null, 'Checklist v2 issued, DOC-PV-113.') as c1e \gset
select pg_temp.q_refused(format('select deviation_step(%L, %L, %L, %L)', :'d1', 'closed', 'approved', 'Done')) as close_done_capa \gset
select capa_step(:'c1', 'effective', 'done', 'No late case in four weeks.') as c1f \gset
select deviation_step(:'d1', 'closed', 'approved', 'Every CAPA effective.') as closed \gset
select pg_temp.q_refused(format('select deviation_update(%L, %L, %L)', :'d1', 'closed', '{"root_cause":"y"}')) as closed_kept \gset
reset role;
select pg_temp.q_assert(:'back' = 'investigating' and :'again' = 'capa' and :'appr' = 'approved'
    and (select qa_satisfactory and approved_by = :'reviewer_id'::uuid from deviation where id = :'d1'),
  'not satisfactory sends it back to the investigation; satisfactory approves it');
select pg_temp.q_assert(:'close_open_capa' like '22023%still open%' and :'close_done_capa' like '22023%still open%',
  'a deviation cannot close while a CAPA of it is not effective');
select pg_temp.q_assert(:'no_evidence' like '22023%evidence%', 'a CAPA is done only with its evidence');
select pg_temp.q_assert(:'c1d' = 'in_progress' and :'c1f' = 'effective'
    and (select verified_by = :'reviewer_id'::uuid and done_on is not null from capa where id = :'c1'),
  'not effective sends a CAPA back to in progress; effective is verified by a person');
select pg_temp.q_assert(:'closed' = 'closed' and :'closed_kept' like '22023%', 'then it closes, and is kept as it is');

-- ───────────── audits: the deadlines count from the day the report was received ─────────────
-- Received 11 days ago: review (day 1) was done, meeting (day 2) was not; draft CAPA (day 10) is late by 1 day;
-- approval (day 12) is due tomorrow; submission (day 14) in 3 days.
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select audit_update(:'a1', 'report_received', jsonb_build_object('reviewed_on', :'today'::date - 10)) as au1 \gset
select pg_temp.q_refused(format('select audit_update(%L, %L, %L)', :'a1', 'report_received',
  jsonb_build_object('meeting_on', :'today'::date + 1))) as au_future \gset
select pg_temp.q_refused(format('select audit_update(%L, %L, %L)', :'a1', 'report_received',
  jsonb_build_object('meeting_on', :'today'::date - 20))) as au_before \gset
select pg_temp.q_refused(format('select audit_step(%L, %L, %L)', :'a1', 'capa_submitted', 'planned')) as au_stale \gset
select quality_state()::text as qs \gset
reset role;
select pg_temp.q_assert(:'au1' = 'report_received', 'the day the review was done is recorded');
select pg_temp.q_assert(:'au_future' like '22023%future%' and :'au_before' like '22023%on or after%',
  'a day something was done is not in the future, nor before the report');
select pg_temp.q_assert(:'au_stale' like 'PH409%', 'an audit step from a status that moved is refused');
create temp table q_deadlines as
  select d ->> 'key' as key, (d ->> 'due')::date as due, d ->> 'state' as state, (d ->> 'days_left')::int as days_left
    from jsonb_array_elements(:'qs'::jsonb -> 'audits') a,
         jsonb_array_elements(a -> 'deadlines') d
   where a ->> 'id' = :'a1';
select pg_temp.q_assert((select string_agg(key, ',' order by due) from q_deadlines) = 'review,meeting,draft,approval,submission',
  'an audit with its report received has the five deadlines of PV-SOP-022');
select pg_temp.q_assert(
  (select due = :'today'::date - 10 and state = 'done' from q_deadlines where key = 'review')
  and (select due = :'today'::date - 9 and state = 'late' from q_deadlines where key = 'meeting')
  and (select due = :'today'::date - 1 and state = 'late' and days_left = -1 from q_deadlines where key = 'draft')
  and (select due = :'today'::date + 1 and state = 'soon' and days_left = 1 from q_deadlines where key = 'approval')
  and (select due = :'today'::date + 3 and state = 'running' and days_left = 3 from q_deadlines where key = 'submission'),
  'review +1 done, meeting +2 late, draft CAPA +10 late by 1 day, approval +12 due tomorrow, submission +14 in 3 days');
select pg_temp.q_assert(
  (select c ->> 'source' = 'audit' and (c ->> 'observation_number')::int = 1 and c ->> 'owner_name' = 'Head of Regulatory Affairs'
          and c -> 'due' ->> 'state' = 'running'
     from jsonb_array_elements(:'qs'::jsonb -> 'capas') c where c ->> 'id' = :'c2')
  and (select c ->> 'deviation_ref' = 'D001/' || :yr and c -> 'due' ->> 'state' = 'done'
     from jsonb_array_elements(:'qs'::jsonb -> 'capas') c where c ->> 'id' = :'c1'),
  'the CAPA plan names each source and its due state');
select pg_temp.q_assert((:'qs'::jsonb -> 'capas' -> 0 ->> 'id') = :'c2',
  'the CAPA plan lists open ones before the done ones');

-- An audit closes only with its closure confirmed and every CAPA effective.
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select audit_step(:'a1', 'capa_submitted', 'report_received', null, :'today'::date) as au2 \gset
select pg_temp.q_refused(format('select audit_step(%L, %L, %L, %L, %L)', :'a1', 'closed', 'capa_submitted',
  'Closed by the lead auditor', :'today')) as au_close_open \gset
reset role;
select pg_temp.q_assert(:'au2' = 'capa_submitted' and :'au_close_open' like '22023%still open%',
  'an audit cannot close while a CAPA of it is open');

-- ───────────── the history: written by every step, never changed ─────────────
select count(*) as d1_events from quality_event where record_kind = 'deviation' and record_id = :'d1' \gset
select count(*) as c1_events from quality_event where record_kind = 'capa' and record_id = :'c1' \gset
select pg_temp.q_assert(:d1_events = 9,
  'every deviation step is in the history (opened, investigating, level, updated, capa, not satisfactory, capa, approved, closed); a refused one is not: ' || :d1_events);
select pg_temp.q_assert(:c1_events = 7, 'every CAPA step is in the history: ' || :c1_events);
select pg_temp.q_assert(
  (select before ->> 'level' is null and (after ->> 'level')::int = 2 and comment like 'May affect%'
     from quality_event where record_id = :'d1' and step = 'level_set'),
  'a change keeps what it was before and after, with the comment');
select pg_temp.q_refused('update quality_event set comment = ''changed''') as ev_update \gset
select pg_temp.q_refused('delete from quality_event') as ev_delete \gset
select pg_temp.q_refused('truncate quality_event') as ev_truncate \gset
select pg_temp.q_as('00000000-0000-0000-0000-0000000000a1');
set role authenticated;
select pg_temp.q_refused($q$insert into quality_event (record_kind, record_id, step, person_id)
  values ('deviation', gen_random_uuid(), 'opened', my_person_id())$q$) as ev_insert \gset
reset role;
select pg_temp.q_assert(:'ev_update' like '%append-only%' and :'ev_delete' like '%append-only%'
    and :'ev_truncate' like '%append-only%',
  'the history cannot be updated, deleted or emptied, even by the owner');
select pg_temp.q_assert(:'ev_insert' like '42501%', 'nobody writes the history from the app, not even an administrator');
select pg_temp.q_assert(
  (select count(*) from audit_log where table_name = 'deviation' and row_pk = :'d1') >= 5,
  'every change of a deviation is in the audit log too');

-- ───────────── signed out: nothing ─────────────
select set_config('request.jwt.claims', '', false);
set role anon;
select pg_temp.q_refused('select count(*) from deviation') as anon_read \gset
select pg_temp.q_refused('select quality_state()') as anon_state \gset
reset role;
select pg_temp.q_assert(:'anon_read' like '42501%' and :'anon_state' like '42501%',
  'a signed-out visitor reads nothing');
select pg_temp.q_assert(
  not has_table_privilege('service_role', 'public.capa', 'select')
    and not has_table_privilege('authenticated', 'public.capa', 'insert')
    and not has_function_privilege('authenticated', 'public.deviation_open_as(uuid, date, text, text, date, date, boolean, boolean, boolean)', 'execute')
    and not has_function_privilege('anon', 'public.capa_step(uuid, text, text, text, date, text)', 'execute')
    and has_function_privilege('authenticated', 'public.capa_step(uuid, text, text, text, date, text)', 'execute'),
  'only the functions write; the service key holds no right on the quality records');

rollback;
