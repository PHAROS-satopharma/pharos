-- PHAROS CI — proposed deviations (0108): a deadline PHAROS kept that passed unmet is proposed once; a reviewer
-- records it as a numbered deviation or dismisses it with a reason; PHAROS never records one itself.
-- Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.
-- One transaction, rolled back at the end.

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

-- PHAROS looks from 30 days ago (in production: the day 0108 ran).
update app_setting set value = to_jsonb((:'today'::date - 30)::text) where key = 'deviation_proposals_since';

-- ───────────── the records whose deadlines pass ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_open('Late case entry', 'A serious case was entered on day 16.', null, :'today'::date) as d1 \gset
select capa_open(:'d1', null, 'Re-train the case team', null, null, 'QA Manager', :'today'::date) as c_late \gset
select capa_open(:'d1', null, 'Check the old cases', null, null, 'QA Manager', :'today'::date) as c_old \gset
select capa_open(:'d1', null, 'Not late yet', null, null, 'QA Manager', :'today'::date) as c_today \gset
-- Report received five days ago: the review (+1) and the meeting (+2) are late, the draft CAPA (+10) is not.
select audit_open('external', 'Partner audit', 'Partner Pharma (MAH)', null, null, null, null,
                  :'today'::date - 5) as a1 \gset
reset role;
-- Due days in the past (a CAPA is opened due today or later; the clock moved on).
update capa set due_on = :'today'::date - 3 where id = :'c_late';
update capa set due_on = :'today'::date - 40 where id = :'c_old';      -- before PHAROS began to look

-- ───────────── the daily run ─────────────
select count(*) as devs_before from deviation \gset
select deviation_proposals_find(:'today'::date) as first_run \gset
select deviation_proposals_find(:'today'::date) as second_run \gset
select count(*) filter (where source_id = :'c_late') as p_capa_late,
       count(*) filter (where source_id = :'c_old') as p_capa_old,
       count(*) filter (where source_id = :'c_today') as p_capa_today,
       count(*) filter (where source_id = :'a1') as p_audit,
       string_agg(source_step, ',' order by source_step) filter (where source_id = :'a1') as audit_steps
  from deviation_proposal \gset
select pg_temp.q_assert(:first_run >= 3 and :second_run = 0, 'the run proposes once, and a second run adds nothing');
select pg_temp.q_assert(:p_capa_late = 1, 'a CAPA past its due day is proposed');
select pg_temp.q_assert(:p_capa_old = 0, 'a deadline missed before PHAROS began to look is never proposed');
select pg_temp.q_assert(:p_capa_today = 0, 'a CAPA due today is not missed yet');
select pg_temp.q_assert(:p_audit = 2 and :'audit_steps' = 'meeting,review',
  'the audit''s review and meeting are proposed, the draft CAPA not yet');
select pg_temp.q_assert(
  (select status = 'proposed' and occurred_on = :'today'::date - 3 and detected_on = :'today'::date
          and regulatory_compliance and description like '%was due on%'
     from deviation_proposal where source_id = :'c_late'),
  'a proposal carries the day it fell due, the day it was found and its words');
select pg_temp.q_assert(:devs_before = (select count(*) from deviation),
  'the run records no deviation by itself');

select id as p_capa from deviation_proposal where source_id = :'c_late' \gset
select id as p_review from deviation_proposal where source_id = :'a1' and source_step = 'review' \gset
select id as p_meeting from deviation_proposal where source_id = :'a1' and source_step = 'meeting' \gset

-- ───────────── a reader reads and decides nothing; nobody runs the finder ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select jsonb_array_length(deviation_proposals()) as reader_sees \gset
select pg_temp.q_refused(format('select deviation_proposal_dismiss(%L, %L)', :'p_capa', 'no')) as r1 \gset
select pg_temp.q_refused(format('select deviation_proposal_confirm(%L, %L, %L, null, %L)',
                                :'p_capa', 't', 'd', :'today')) as r2 \gset
select pg_temp.q_refused('select deviation_proposals_find()') as r3 \gset
select pg_temp.q_refused(format('update deviation_proposal set status = %L where id = %L', 'dismissed', :'p_capa')) as r4 \gset
reset role;
select pg_temp.q_assert(:reader_sees >= 3, 'a reader reads the proposed deviations');
select pg_temp.q_assert(:'r1' like '42501%' and :'r2' like '42501%',
  'a reader can neither record nor dismiss a proposal');
select pg_temp.q_assert(:'r3' like '42501%' and :'r4' like '42501%',
  'no signed-in person runs the finder or writes the table');

-- ───────────── the reviewer records one, dismisses one ─────────────
select pg_temp.q_as('00000000-0000-0000-0000-0000000000c3');
set role authenticated;
select deviation_proposal_confirm(:'p_capa', 'CAPA-late: re-training not done',
                                  'The re-training CAPA passed its due day.', :'today'::date - 3, :'today'::date,
                                  false, true, false) as new_dev \gset
select pg_temp.q_refused(format('select deviation_proposal_confirm(%L, %L, %L, null, %L)',
                                :'p_capa', 't', 'd', :'today')) as twice \gset
select pg_temp.q_refused(format('select deviation_proposal_dismiss(%L, %L)', :'p_review', '  ')) as no_reason \gset
select deviation_proposal_dismiss(:'p_review', 'The review was held on time; the day was not entered.') as dismissed \gset
select pg_temp.q_refused(format('select deviation_proposal_dismiss(%L, %L)', :'p_review', 'again')) as dismiss_twice \gset
select p ->> 'deviation_ref' as confirmed_ref, p ->> 'decided_by' as decided_by
  from jsonb_array_elements(deviation_proposals()) p where p ->> 'id' = :'p_capa' \gset
select (deviation_proposals() -> 0 ->> 'status') as first_status \gset
reset role;
select pg_temp.q_assert(
  (select d.title = 'CAPA-late: re-training not done' and d.status = 'open' and d.ref like 'D%/%'
     from deviation d where d.id = :'new_dev'),
  'recording a proposal opens a numbered deviation with what she wrote');
select pg_temp.q_assert(
  (select status = 'confirmed' and deviation_id = :'new_dev' and decided_at is not null
     from deviation_proposal where id = :'p_capa')
  and :'confirmed_ref' is not null and :'decided_by' is not null,
  'the proposal is linked to its deviation, with who decided');
select pg_temp.q_assert(exists (select 1 from quality_event where record_kind = 'deviation' and record_id = :'new_dev'
                                                         and step = 'opened'),
  'the deviation has its history from the first step');
select pg_temp.q_assert(:'twice' like 'PH409%' and :'dismiss_twice' like 'PH409%',
  'a decided proposal is not decided again');
select pg_temp.q_assert(:'no_reason' like '22023%', 'dismissing needs a reason');
select pg_temp.q_assert(
  (select status = 'dismissed' and dismissed_reason like 'The review was held%' from deviation_proposal
    where id = :'p_review'),
  'a dismissed proposal keeps its reason');
select pg_temp.q_assert(:'first_status' = 'proposed', 'the tab lists the proposals still waiting first');

-- The next day: the dismissed and the recorded are not proposed again.
select deviation_proposals_find(:'today'::date + 1) as next_day \gset
select pg_temp.q_assert(
  (select count(*) from deviation_proposal where id in (:'p_capa', :'p_review')) = 2
  and (select count(*) from deviation_proposal where source_id in (:'c_late', :'a1')
                                               and source_step in ('review', (:'today'::date - 3)::text)) = 2,
  'a decided missed deadline is never proposed again');

rollback;
