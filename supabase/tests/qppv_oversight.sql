-- PHAROS CI — what is late for the QPPV (0029). Runs on the database ci.yml prepared: the people CI Admin
-- (…a1) and CI Reader (…b2) exist.

create function pg_temp.qo_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

insert into ingredient (id, inn_en) values ('00000000-0000-0000-0000-0000000f0a01', 'CI latine');
-- A signal whose validation was due on 1 January 2025, and one closed long ago.
insert into signal (id, ref, title, ingredient_id, opened_by, validation_due) values
  ('00000000-0000-0000-0000-0000000f0b01', 'SIG-CI-LATE', 'Late signal', '00000000-0000-0000-0000-0000000f0a01',
   '00000000-0000-0000-0000-0000000000a1', '2025-01-01');
insert into signal (id, ref, title, opened_by, validation_due, stage, outcome, closed_at) values
  ('00000000-0000-0000-0000-0000000f0b02', 'SIG-CI-DONE', 'Closed signal', '00000000-0000-0000-0000-0000000000a1',
   '2025-01-01', 'closed', 'refuted', '2025-01-02 10:00+00');
-- Notices found on 1 January (late after 7 days) and on 15 January (not yet), and an old one from a backfill.
insert into issue (id, doc_type, title, status, is_backfill, created_at) values
  ('00000000-0000-0000-0000-0000000f0c01', 'dhpc', 'Old notice', 'new', false, '2025-01-01 08:00+00'),
  ('00000000-0000-0000-0000-0000000f0c02', 'dhpc', 'Recent notice', 'new', false, '2025-01-15 08:00+00'),
  ('00000000-0000-0000-0000-0000000f0c03', 'dhpc', 'Backfill notice', 'new', true, '2025-01-01 08:00+00'),
  ('00000000-0000-0000-0000-0000000f0c04', 'dhpc', 'Reviewed notice', 'reviewed', false, '2025-01-01 08:00+00');
insert into issue_ingredient values ('00000000-0000-0000-0000-0000000f0c01', '00000000-0000-0000-0000-0000000f0a01');
insert into eurd_entry (eurd_id, ingredient_id, substance, frequency, dlp, submission_date, list_version, sha256, r2_key)
  values (9922, '00000000-0000-0000-0000-0000000f0a01', 'ci latine', '3 years', '2025-03-01', '2025-05-30',
          'EMA/630645/2012 Rev.165', 'cd', 'raw/cd');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select days_late as qo_sig from overdue_items('2025-01-20') where ref_id = '00000000-0000-0000-0000-0000000f0b01' \gset
select count(*) as qo_closed from overdue_items('2025-01-20') where ref_id = '00000000-0000-0000-0000-0000000f0b02' \gset
select days_late as qo_rev, due as qo_due, ingredient as qo_ing
  from overdue_items('2025-01-20') where ref_id = '00000000-0000-0000-0000-0000000f0c01' \gset
select count(*) as qo_quiet from overdue_items('2025-01-20')
 where ref_id in ('00000000-0000-0000-0000-0000000f0c02', '00000000-0000-0000-0000-0000000f0c03',
                  '00000000-0000-0000-0000-0000000f0c04') \gset
select count(*) as qo_psur, min(days_late) as qo_left from overdue_items('2025-01-20')
 where kind = 'psur' and ref_id = '00000000-0000-0000-0000-0000000f0a01' \gset
reset role;

update app_setting set value = '30' where key = 'review_due_days';
select count(*) as qo_longer from overdue_items('2025-01-20') where ref_id = '00000000-0000-0000-0000-0000000f0c01' \gset
update app_setting set value = '7' where key = 'review_due_days';

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as qo_stranger from overdue_items('2025-01-20') \gset
reset role;

select pg_temp.qo_assert(:qo_sig = 19, 'a signal due on 1 January is 19 days late on the 20th');
select pg_temp.qo_assert(:qo_closed = 0, 'a closed signal is never late');
select pg_temp.qo_assert(:qo_rev = 12 and :'qo_due' = '2025-01-08' and :'qo_ing' = 'CI latine',
  'a notice still new 7 days after it was found is late, with its ingredient');
select pg_temp.qo_assert(:qo_quiet = 0, 'a recent, a backfilled or a reviewed notice is not late');
select pg_temp.qo_assert(:qo_psur = 1 and :qo_left = -40,
  'a PSUR data lock point in the next 90 days is listed with its days left, the submission after 90 days is not');
select pg_temp.qo_assert(:qo_longer = 0, 'review_due_days moves the review due date');
select pg_temp.qo_assert(:qo_stranger = 0, 'someone not on the team sees nothing late');

-- The escalation is a notification kind of its own.
insert into notification (kind, dry_run, summary) values ('escalation', true, 'CI escalation');
delete from notification where summary = 'CI escalation';

delete from signal where id in ('00000000-0000-0000-0000-0000000f0b01', '00000000-0000-0000-0000-0000000f0b02');
delete from issue where id::text like '00000000-0000-0000-0000-0000000f0c0%';
delete from ingredient where id = '00000000-0000-0000-0000-0000000f0a01';
