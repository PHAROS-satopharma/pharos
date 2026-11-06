-- PHAROS CI — the five-day clock to the Egyptian Drug Authority (0041): finding_state(), authority_report and
-- v_eda_clock. Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3)
-- exist. Everything here happens in one transaction that is rolled back at the end (review_event and
-- authority_report cannot be deleted).

begin;

create function pg_temp.ec_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ec_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- Noon in Cairo, n days before today's Cairo date: a first_seen_at whose Cairo day is certain.
create function pg_temp.ec_noon_ago(n int) returns timestamptz language sql stable as $$
  select ((signal_cairo_today() - n)::timestamp + interval '12 hours') at time zone 'Africa/Cairo'
$$;

select signal_cairo_today() as today \gset

-- ───────────── one ingredient, one authority, four notices ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000041a001', 'CI clockamine', 'Z97ZZ01');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-00000041c001', '00000000-0000-0000-0000-00000041a001', 'en', 'CI clockamine');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-EC-A', 'XC', 'CI Clockland', 'CI Clockland Agency', '{en}', 'https://clock.example.test/');
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-ec-html', 'CI-EC-A', 'safety', 'html', 'https://clock.example.test/alerts', 'generic_html', '{en}',
   'https://clock.example.test/alerts', true);
-- b001: first shown yesterday; b002: ten days ago (late); b003: yesterday, never decided; b004: three days ago
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, first_seen_at) values
  ('00000000-0000-0000-0000-00000041b001', 'ci-ec-html', 'c1', 'https://clock.example.test/alerts/1',
   'CI clockamine: a new warning', 'en', 'dhpc', pg_temp.ec_noon_ago(1)),
  ('00000000-0000-0000-0000-00000041b002', 'ci-ec-html', 'c2', 'https://clock.example.test/alerts/2',
   'CI clockamine: an old warning', 'en', 'safety_alert', pg_temp.ec_noon_ago(10)),
  ('00000000-0000-0000-0000-00000041b003', 'ci-ec-html', 'c3', 'https://clock.example.test/alerts/3',
   'CI clockamine: nobody decided', 'en', 'dhpc', pg_temp.ec_noon_ago(1)),
  ('00000000-0000-0000-0000-00000041b004', 'ci-ec-html', 'c4', 'https://clock.example.test/alerts/4',
   'CI clockamine: sent and withdrawn', 'en', 'dhpc', pg_temp.ec_noon_ago(3));
insert into match (document_id, ingredient_id, term_id, field, matched_text)
select d.id, '00000000-0000-0000-0000-00000041a001', '00000000-0000-0000-0000-00000041c001', 'title', 'CI clockamine'
  from document d where d.source_id = 'ci-ec-html';
insert into issue (id, doc_type, title, anchor_document_id, first_date) values
  ('00000000-0000-0000-0000-00000041e001', 'dhpc', 'CI clockamine: a new warning',
   '00000000-0000-0000-0000-00000041b001', :'today'::date - 1),
  ('00000000-0000-0000-0000-00000041e002', 'safety_alert', 'CI clockamine: an old warning',
   '00000000-0000-0000-0000-00000041b002', :'today'::date - 10),
  ('00000000-0000-0000-0000-00000041e003', 'dhpc', 'CI clockamine: nobody decided',
   '00000000-0000-0000-0000-00000041b003', :'today'::date - 1),
  ('00000000-0000-0000-0000-00000041e004', 'dhpc', 'CI clockamine: sent and withdrawn',
   '00000000-0000-0000-0000-00000041b004', :'today'::date - 3);
insert into issue_document (issue_id, document_id, link, method)
select i.id, i.anchor_document_id, 'anchor', 'auto' from issue i where i.id::text like '00000000-0000-0000-0000-00000041e%';
insert into issue_ingredient (issue_id, ingredient_id)
select i.id, '00000000-0000-0000-0000-00000041a001' from issue i where i.id::text like '00000000-0000-0000-0000-00000041e%';

-- ───────────── the settings ─────────────
select pg_temp.ec_assert((select value from app_setting where key = 'eda_days') = '5'::jsonb
    and (select value #>> '{}' from app_setting where key = 'eda_day_zero') = 'first_seen',
  'the authority has 5 days, counted from the day PHAROS first showed the notice');

-- ───────────── no decision: the clock is off, day zero is still known ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select finding_state(array['00000000-0000-0000-0000-00000041e003']::uuid[])::text as ec_undecided \gset
select finding_state('{}'::uuid[])::text as ec_empty \gset
select finding_state(array['00000000-0000-0000-0000-00000041ffff']::uuid[])::text as ec_unknown \gset
reset role;
select pg_temp.ec_assert(:'ec_undecided'::jsonb -> '00000000-0000-0000-0000-00000041e003' ->> 'clock' = 'off'
    and (:'ec_undecided'::jsonb -> '00000000-0000-0000-0000-00000041e003' ->> 'day_zero')::date = :'today'::date - 1
    and (:'ec_undecided'::jsonb -> '00000000-0000-0000-0000-00000041e003' ->> 'due')::date = :'today'::date + 4
    and :'ec_undecided'::jsonb -> '00000000-0000-0000-0000-00000041e003' -> 'sent' = 'null'::jsonb,
  'a notice nobody decided has its clock off; day zero is the Cairo day it was first shown');
select pg_temp.ec_assert(:'ec_empty' = '{}' and :'ec_unknown' = '{}',
  'no ids, or an unknown id, gives an empty answer and never an error');

-- ───────────── Concerns us starts the clock ─────────────
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id) values
  ('00000000-0000-0000-0000-00000041e001', 'new', 'relevant', 'Our tablets carry it', my_person_id()),
  ('00000000-0000-0000-0000-00000041e002', 'new', 'relevant', null, my_person_id()),
  ('00000000-0000-0000-0000-00000041e004', 'new', 'relevant', null, my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000041e001', '00000000-0000-0000-0000-00000041e002',
                           '00000000-0000-0000-0000-00000041e003', '00000000-0000-0000-0000-00000041e004']::uuid[])::text
  as ec_running \gset
reset role;
select pg_temp.ec_assert(:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'clock' = 'running'
    and (:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'days_left')::int = 4
    and (:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'due')::date = :'today'::date + 4,
  'Concerns us on a notice first shown yesterday: the clock runs, 4 days left');
select pg_temp.ec_assert(:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e002' ->> 'clock' = 'late'
    and (:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e002' ->> 'days_left')::int = -5,
  'a notice first shown ten days ago is late by 5 days');
select pg_temp.ec_assert(:'ec_running'::jsonb -> '00000000-0000-0000-0000-00000041e003' ->> 'clock' = 'off',
  'the undecided notice stays off');

-- ───────────── Sent to the authority ─────────────
-- A reader cannot record it; a reviewer records only as herself; a notice whose clock is off refuses it.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ec_refused($q$insert into authority_report (issue_id, sent_on, person_id)
  values ('00000000-0000-0000-0000-00000041e001', signal_cairo_today(), my_person_id())$q$) as ec_reader_sends \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ec_refused($q$insert into authority_report (issue_id, sent_on, person_id)
  values ('00000000-0000-0000-0000-00000041e001', signal_cairo_today(),
          (select id from person where email = 'admin@example.test'))$q$) as ec_as_other \gset
select pg_temp.ec_refused($q$insert into authority_report (issue_id, sent_on, person_id)
  values ('00000000-0000-0000-0000-00000041e003', signal_cairo_today(), my_person_id())$q$) as ec_off_sends \gset
select pg_temp.ec_refused($q$insert into authority_report (issue_id, sent_on, person_id)
  values ('00000000-0000-0000-0000-00000041e001', signal_cairo_today() + 1, my_person_id())$q$) as ec_tomorrow \gset
insert into authority_report (issue_id, sent_on, reference, note, person_id)
  values ('00000000-0000-0000-0000-00000041e001', signal_cairo_today(), 'EDA/2026/0042', 'By e-mail to the EDA',
          my_person_id());
select pg_temp.ec_refused($q$insert into authority_report (issue_id, sent_on, person_id)
  values ('00000000-0000-0000-0000-00000041e001', signal_cairo_today(), my_person_id())$q$) as ec_twice \gset
select finding_state(array['00000000-0000-0000-0000-00000041e001']::uuid[])::text as ec_sent \gset
select pg_temp.ec_refused($q$update authority_report set reference = 'changed'$q$) as ec_update_as_reviewer \gset
select pg_temp.ec_refused($q$delete from authority_report$q$) as ec_delete_as_reviewer \gset
reset role;
-- Even the owner of the table (the collector's direct connection) cannot change or delete a report.
select pg_temp.ec_refused($q$update authority_report set reference = 'changed'$q$) as ec_update \gset
select pg_temp.ec_refused($q$delete from authority_report$q$) as ec_delete \gset
select pg_temp.ec_assert(:'ec_reader_sends' like '42501%' and :'ec_as_other' like '42501%',
  'a reader cannot record a report to the authority; a reviewer records only her own');
select pg_temp.ec_assert(:'ec_off_sends' like 'PH409 NO_CONCERN%',
  'a notice whose latest decision is not Concerns us cannot be reported as sent (PH409, NO_CONCERN)');
select pg_temp.ec_assert(:'ec_tomorrow' like '22023%', 'a report cannot be dated in the future');
select pg_temp.ec_assert(:'ec_twice' like 'PH409 ALREADY_SENT%',
  'a notice already reported for this decision is not reported twice (PH409, ALREADY_SENT)');
select pg_temp.ec_assert(:'ec_sent'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'clock' = 'sent'
    and (:'ec_sent'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' ->> 'on')::date = :'today'::date
    and :'ec_sent'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' ->> 'reference' = 'EDA/2026/0042'
    and :'ec_sent'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' ->> 'person' = 'CI Reviewer'
    and :'ec_sent'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' ->> 'note' = 'By e-mail to the EDA',
  'a report stops the clock: sent, when, by whom, under which reference');
select pg_temp.ec_assert(:'ec_update_as_reviewer' like '42501%' and :'ec_delete_as_reviewer' like '42501%',
  'a reviewer has no right to change or delete a report to the authority');
select pg_temp.ec_assert(:'ec_update' like '%append-only%' and :'ec_delete' like '%append-only%',
  'authority_report is append-only, even for the owner of the table');
select pg_temp.ec_assert(
  (select count(*) from audit_log where table_name = 'authority_report' and action = 'INSERT'
      and new_row ->> 'reference' = 'EDA/2026/0042') = 1,
  'the report to the authority is in the audit log');
select pg_temp.ec_assert(
  (select ar.decision_id = (select re.id from review_event re where re.issue_id = ar.issue_id
                              order by re.created_at desc, re.id desc limit 1)
     from authority_report ar where ar.issue_id = '00000000-0000-0000-0000-00000041e001'),
  'the report names the decision it answers');

-- ───────────── a decision changed switches the clock off; Concerns us again starts a new clock ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id)
  values ('00000000-0000-0000-0000-00000041e001', 'relevant', 'not_relevant', 'CI: read again, not ours', my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000041e001']::uuid[])::text as ec_reversed \gset
insert into review_event (issue_id, from_status, to_status, comment, person_id)
  values ('00000000-0000-0000-0000-00000041e001', 'not_relevant', 'relevant', 'CI: ours after all', my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000041e001']::uuid[])::text as ec_again \gset
reset role;
select pg_temp.ec_assert(:'ec_reversed'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'clock' = 'off'
    and :'ec_reversed'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' = 'null'::jsonb,
  'Doesn''t concern us switches the clock off; the earlier report belongs to the earlier decision');
select pg_temp.ec_assert(:'ec_again'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'clock' = 'running'
    and :'ec_again'::jsonb -> '00000000-0000-0000-0000-00000041e001' -> 'sent' = 'null'::jsonb,
  'Concerns us again starts the clock again: the authority has not heard of this decision');

-- ───────────── a wrong "sent" is withdrawn, never deleted ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
insert into authority_report (id, issue_id, sent_on, reference, person_id)
  values ('00000000-0000-0000-0000-00000041d004', '00000000-0000-0000-0000-00000041e004', signal_cairo_today() - 1,
          'EDA/2026/0043', my_person_id());
select finding_state(array['00000000-0000-0000-0000-00000041e004']::uuid[])::text as ec_sent4 \gset
select pg_temp.ec_refused($q$select withdraw_authority_report('00000000-0000-0000-0000-00000041d004', '  ')$q$) as ec_no_reason \gset
select withdraw_authority_report('00000000-0000-0000-0000-00000041d004', 'Wrong notice, sent for another one');
select pg_temp.ec_refused($q$select withdraw_authority_report('00000000-0000-0000-0000-00000041d004', 'again')$q$) as ec_withdraw_twice \gset
select finding_state(array['00000000-0000-0000-0000-00000041e004']::uuid[])::text as ec_withdrawn \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ec_refused($q$select withdraw_authority_report('00000000-0000-0000-0000-00000041d004', 'reader')$q$) as ec_reader_withdraws \gset
reset role;
select pg_temp.ec_assert(:'ec_sent4'::jsonb -> '00000000-0000-0000-0000-00000041e004' ->> 'clock' = 'sent',
  'the fourth notice was reported');
select pg_temp.ec_assert(:'ec_no_reason' like '22023%', 'a withdrawal needs a reason');
select pg_temp.ec_assert(:'ec_withdrawn'::jsonb -> '00000000-0000-0000-0000-00000041e004' ->> 'clock' = 'running'
    and (:'ec_withdrawn'::jsonb -> '00000000-0000-0000-0000-00000041e004' ->> 'days_left')::int = 2
    and :'ec_withdrawn'::jsonb -> '00000000-0000-0000-0000-00000041e004' -> 'sent' = 'null'::jsonb,
  'a withdrawn report starts the clock again; the row stays');
select pg_temp.ec_assert(:'ec_withdraw_twice' like 'P0002%' and :'ec_reader_withdraws' like '42501%',
  'a report is withdrawn once, by a reviewer or administrator');
select pg_temp.ec_assert(
  (select withdrawn_at is not null and withdraw_reason = 'Wrong notice, sent for another one'
          and withdrawn_by = (select id from person where email = 'reviewer@example.test')
     from authority_report where id = '00000000-0000-0000-0000-00000041d004'),
  'the withdrawal names who withdrew it and why');
select pg_temp.ec_refused($q$update authority_report set withdrawn_at = null where id = '00000000-0000-0000-0000-00000041d004'$q$)
  as ec_unwithdraw \gset
select pg_temp.ec_assert(:'ec_unwithdraw' like '%append-only%', 'a withdrawal cannot be undone by hand');

-- ───────────── the view for the collectors agrees with finding_state ─────────────
select string_agg(issue_id::text || ':' || clock || ':' || days_left || ':' || ingredient || ':' || country
                  || ':' || coalesce(decided_by, '-'), ' ' order by due, issue_id) as ec_view
  from v_eda_clock where issue_id::text like '00000000-0000-0000-0000-00000041e%' \gset
select pg_temp.ec_assert(:'ec_view' =
    '00000000-0000-0000-0000-00000041e002:late:-5:CI clockamine:CI Clockland:CI Admin '
    || '00000000-0000-0000-0000-00000041e004:running:2:CI clockamine:CI Clockland:CI Admin '
    || '00000000-0000-0000-0000-00000041e001:running:4:CI clockamine:CI Clockland:CI Admin',
  'the collectors'' view lists the running and late clocks with ingredient, country and who said Concerns us, '
  || 'never one that is off or sent');
select pg_temp.ec_assert(
  (select ingredient_id = '00000000-0000-0000-0000-00000041a001' and title = 'CI clockamine: an old warning'
          and day_zero = :'today'::date - 10 and due = :'today'::date - 5
     from v_eda_clock where issue_id = '00000000-0000-0000-0000-00000041e002'),
  'the view carries the ingredient id for the link, the title, day zero and the due day');

-- ───────────── the report reads it through a direct connection; strangers are refused ─────────────
select set_config('request.jwt.claims', '', false);
select finding_state(array['00000000-0000-0000-0000-00000041e002']::uuid[])::text as ec_direct \gset
select pg_temp.ec_assert(:'ec_direct'::jsonb -> '00000000-0000-0000-0000-00000041e002' ->> 'clock' = 'late',
  'the weekly report reads the clock through its direct connection');
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ec_refused($q$select finding_state(array['00000000-0000-0000-0000-00000041e002']::uuid[])$q$) as ec_stranger \gset
select pg_temp.ec_refused($q$select * from v_eda_clock$q$) as ec_stranger_view \gset
-- psql unsets a variable for a null, so a query that is not refused answers 'allowed'
select coalesce(pg_temp.ec_refused($q$select count(*) from authority_report$q$), 'allowed') as ec_stranger_rows \gset
reset role;
set role anon;
select pg_temp.ec_refused($q$select finding_state('{}'::uuid[])$q$) as ec_anon \gset
select pg_temp.ec_refused($q$select count(*) from authority_report$q$) as ec_anon_rows \gset
reset role;
select set_config('request.jwt.claims', '', false);
select pg_temp.ec_assert(:'ec_stranger' like '42501%' and :'ec_stranger_view' like '42501%'
    and :'ec_anon' like '42501%' and :'ec_anon_rows' like '42501%',
  'someone signed in but not on the team, and signed-out visitors, read nothing of the clock');
select pg_temp.ec_assert(:'ec_stranger_rows' = 'allowed' and (
  select count(*) from authority_report) > 0, 'row-level security hides authority_report from a stranger');
select pg_temp.ec_assert(
  has_function_privilege('authenticated', 'public.finding_state(uuid[])', 'execute')
    and has_function_privilege('authenticated', 'public.withdraw_authority_report(uuid, text)', 'execute')
    and not has_function_privilege('anon', 'public.finding_state(uuid[])', 'execute')
    and not has_function_privilege('authenticated', 'public.eda_clock(uuid[])', 'execute')
    and not has_table_privilege('authenticated', 'public.v_eda_clock', 'select')
    and not has_table_privilege('anon', 'public.v_eda_clock', 'select'),
  'the app calls finding_state and the withdrawal; the view and eda_clock are the collectors'' own');

-- ───────────── the settings decide the days and day zero ─────────────
update app_setting set value = '3' where key = 'eda_days';
select finding_state(array['00000000-0000-0000-0000-00000041e001']::uuid[])::text as ec_three \gset
update app_setting set value = '5' where key = 'eda_days';
update app_setting set value = '"decision"' where key = 'eda_day_zero';
select finding_state(array['00000000-0000-0000-0000-00000041e001']::uuid[])::text as ec_from_decision \gset
update app_setting set value = '"first_seen"' where key = 'eda_day_zero';
select pg_temp.ec_assert((:'ec_three'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'days_left')::int = 2,
  'eda_days sets the clock: 3 days from yesterday leaves 2');
select pg_temp.ec_assert((:'ec_from_decision'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'day_zero')::date = :'today'::date
    and (:'ec_from_decision'::jsonb -> '00000000-0000-0000-0000-00000041e001' ->> 'days_left')::int = 5,
  'eda_day_zero = decision counts from the day of the decision instead');

rollback;
