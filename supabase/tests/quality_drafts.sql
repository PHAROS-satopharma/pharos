-- PHAROS CI — a drafted root cause and CAPA (0109): a reviewer asks; one draft waits per record; a reader is
-- refused; a closed record takes none; the tab reads the latest draft of each record; nobody writes the table.
-- Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.

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

select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_open('Late case entry', 'A serious case was entered on day 16 instead of day 15.',
                      null, :'today'::date) as d1 \gset
select audit_open('external', 'Partner audit', 'Partner Pharma (MAH)', null, null, null, null,
                  :'today'::date - 2) as a1 \gset
select audit_add_observation(:'a1', 'The signal log was not reviewed monthly.', 'major') as o1 \gset

select quality_draft_ask('deviation', :'d1') as q1 \gset
select quality_draft_ask('deviation', :'d1') as q1_again \gset
select quality_draft_ask('observation', :'o1') as q2 \gset
select pg_temp.q_refused($q$select quality_draft_ask('capa', gen_random_uuid())$q$) as bad_kind \gset
select pg_temp.q_refused($q$select quality_draft_ask('deviation', gen_random_uuid())$q$) as missing \gset
select pg_temp.q_refused(format('insert into quality_draft (record_kind, record_id, asked_by) values (%L, %L, my_person_id())',
                                'deviation', :'d1')) as direct \gset
select jsonb_array_length(quality_drafts()) as reviewer_sees \gset
reset role;

select pg_temp.q_assert(:'q1' = :'q1_again', 'asking twice while a draft waits returns the same draft');
select pg_temp.q_assert(:'q1' <> :'q2', 'each record has its own draft');
select pg_temp.q_assert(:'bad_kind' like '22023%' and :'missing' like '22023%',
  'a draft is for a deviation or an observation that exists');
select pg_temp.q_assert(:'direct' like '42501%', 'nobody writes the table directly');
select pg_temp.q_assert(:reviewer_sees >= 2, 'the tab reads the drafts');
select pg_temp.q_assert(
  (select status = 'queued' and attempts = 0 and root_cause is null and asked_by is not null
     from quality_draft where id = :'q1'),
  'a new draft waits, empty, with who asked');

-- The collectors finish it (their direct connection); a new ask then makes a new draft.
update quality_draft
   set status = 'ready', root_cause = 'No deputy was named for case entry.', corrective_action = 'Enter the case.',
       preventive_action = 'Name a deputy.', to_check = 'Who was on leave.', model = 'claude-opus-5-5',
       attempts = 1, started_at = now(), finished_at = now()
 where id = :'q1';
select pg_temp.q_refused(format('update quality_draft set status = %L where id = %L', 'ready', :'q2')) as unfinished \gset
select pg_temp.q_assert(:'unfinished' like '23514%', 'a draft is ready only with its root cause');

select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select quality_draft_ask('deviation', :'d1') as q3 \gset
select d ->> 'id' as latest, d ->> 'asked_by' as asked_by from jsonb_array_elements(quality_drafts()) d
 where d ->> 'record_id' = :'d1' \gset
reset role;
select pg_temp.q_assert(:'q3' <> :'q1' and :'latest' = :'q3' and :'asked_by' is not null,
  'after a draft is ready a new ask makes a new one, and the tab shows the latest');

-- A reader reads and asks for nothing.
select pg_temp.q_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select jsonb_array_length(quality_drafts()) as reader_sees \gset
select pg_temp.q_refused(format('select quality_draft_ask(%L, %L)', 'deviation', :'d1')) as reader_ask \gset
reset role;
select pg_temp.q_assert(:reader_sees >= 2 and :'reader_ask' like '42501%', 'a reader reads the drafts and asks for none');

-- A closed audit takes no new draft.
update audit set status = 'closed', capa_submitted_on = :'today'::date, closure_confirmed_on = :'today'::date where id = :'a1';
update quality_draft set status = 'failed', error = 'stopped', finished_at = now() where id = :'q2';
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select pg_temp.q_refused(format('select quality_draft_ask(%L, %L)', 'observation', :'o1')) as closed_ask \gset
reset role;
select pg_temp.q_assert(:'closed_ask' like '22023%', 'a closed record takes no new draft');

rollback;
