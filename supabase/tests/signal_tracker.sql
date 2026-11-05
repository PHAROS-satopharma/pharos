-- PHAROS CI — the signal tracker (0024). Runs after every migration and the acceptance checks in ci.yml,
-- on the same database: the people CI Admin (…a1) and CI Reader (…b2) and the source ci-test exist.

create function pg_temp.sig_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- What the database refuses, as its message (null when it was accepted).
create function pg_temp.refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000000c3', 'reviewer@example.test');
insert into person (auth_user_id, full_name, email, role)
  values ('00000000-0000-0000-0000-0000000000c3', 'CI Reviewer', 'reviewer@example.test', 'reviewer');
insert into ingredient (id, inn_en, atc_code) values ('00000000-0000-0000-0000-00000000051a', 'Cisignaline', 'Z99SG01');
insert into issue (id, doc_type, title, status) values
  ('00000000-0000-0000-0000-000000005101', 'dhpc', 'Relevant letter', 'relevant'),
  ('00000000-0000-0000-0000-000000005102', 'dhpc', 'Second relevant letter', 'relevant'),
  ('00000000-0000-0000-0000-000000005103', 'dhpc', 'Letter still new', 'new');

-- A reader cannot open a signal.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused($q$select open_signal('00000000-0000-0000-0000-000000005101', 'Kidney injury', null)$q$) as r_reader \gset
select pg_temp.refused($q$insert into signal (ref, title, opened_by, validation_due)
  select 'SIG-X', 'Direct', id, current_date from person limit 1$q$) as r_direct \gset
reset role;
select pg_temp.sig_assert(:'r_reader' like '42501%', 'a reader cannot open a signal');
select pg_temp.sig_assert(:'r_direct' is not null and not exists (select 1 from signal where ref = 'SIG-X'),
  'nobody writes the signal table directly');

-- A reviewer opens a signal from a Relevant notice; a notice that is not Relevant cannot open one.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused($q$select open_signal('00000000-0000-0000-0000-000000005103', 'Too early', null)$q$) as r_new \gset
select open_signal('00000000-0000-0000-0000-000000005101', '  Kidney injury  ', '00000000-0000-0000-0000-00000000051a',
                   'Two letters name acute kidney injury') as sig \gset
select pg_temp.refused($q$select open_signal('00000000-0000-0000-0000-000000005101', 'Again', null)$q$) as r_twice \gset
reset role;
select pg_temp.sig_assert(:'r_new' like '%Only a notice marked Relevant%', 'a notice that is not Relevant cannot open a signal');
select pg_temp.sig_assert(:'r_twice' like '%already belongs to a signal%', 'a notice opens one signal at most');
select pg_temp.sig_assert((select ref ~ '^SIG-\d{4}-\d{3}$' and title = 'Kidney injury' and stage = 'validation'
                                  and opened_by = (select id from person where email = 'reviewer@example.test')
                                  and validation_due = (now() at time zone 'Africa/Cairo')::date + 30
                             from signal where id = :'sig'),
  'the signal is numbered, trimmed, opened by the signed-in person, and due for validation in 30 Cairo days');

-- A second notice joins it; a step without a comment, or from a stage already left, is refused.
set role authenticated;
select link_signal_issue(:'sig', '00000000-0000-0000-0000-000000005102', 'Same topic in Spain');
select pg_temp.refused(format($q$select signal_take_step(%L, 'validated', 'validation', '  ', 'high')$q$, :'sig')) as r_nocomment \gset
select pg_temp.refused(format($q$select signal_take_step(%L, 'validated', 'validation', 'Plausible', null)$q$, :'sig')) as r_nopriority \gset
select signal_take_step(:'sig', 'validated', 'validation', 'Plausible mechanism, two authorities', 'high') as st1 \gset
select pg_temp.refused(format($q$select signal_take_step(%L, 'not_validated', 'validation', 'Late click')$q$, :'sig')) as r_stale \gset
reset role;
select pg_temp.sig_assert(:'r_nocomment' like '%needs a comment%', 'a step needs a comment for the record');
select pg_temp.sig_assert(:'r_nopriority' like '%needs a priority%', 'validation needs a priority');
select pg_temp.sig_assert(:'st1' = 'assessment'
    and (select assessment_due from signal where id = :'sig') = (now() at time zone 'Africa/Cairo')::date + 30,
  'a validated high-priority signal is due for assessment in 30 days');
select pg_temp.sig_assert(:'r_stale' like 'PH409 STALE_SIGNAL%', 'a step from a stage already left is refused as stale');
select pg_temp.sig_assert((select notices from v_signal_table where id = :'sig') = 2, 'both notices are behind the signal');

-- Lowering the priority moves the assessment clock; an action needs a due date; closing it ends the signal.
select id as admin_id from person where email = 'admin@example.test' \gset
set role authenticated;
select signal_take_step(:'sig', 'prioritised', 'assessment', 'Only one case so far', 'low');
select signal_take_step(:'sig', 'assigned', 'assessment', null, null, null, :'admin_id');
select pg_temp.refused(format($q$select signal_take_step(%L, 'assessed', 'assessment', 'Update 4.8', null, 'label_update')$q$, :'sig')) as r_nodue \gset
select signal_take_step(:'sig', 'assessed', 'assessment', 'Add AKI to 4.4 and 4.8', null, 'label_update', null,
                        (now() at time zone 'Africa/Cairo')::date + 45) as st2 \gset
select signal_take_step(:'sig', 'action_done', 'action', 'Variation submitted to EDA, ref V-123') as st3 \gset
reset role;
select pg_temp.sig_assert((select assessment_due from signal where id = :'sig') = (now() at time zone 'Africa/Cairo')::date + 90,
  'a low-priority signal is due for assessment 90 days after validation');
select pg_temp.sig_assert(:'r_nodue' like '%needs a due date%', 'an action needs a due date');
select pg_temp.sig_assert(:'st2' = 'action' and :'st3' = 'closed'
    and (select outcome = 'label_update' and closed_at is not null and owner = 'CI Admin' and not overdue
           from v_signal_table where id = :'sig'),
  'assessed with a label update, then closed with the action done');
select pg_temp.sig_assert((select array_agg(step::text order by created_at, id) from signal_event where signal_id = :'sig')
    = array['opened','notice_linked','validated','prioritised','assigned','assessed','action_done'],
  'every step is recorded once, in order');

-- The history is append-only, and an overdue signal says so.
select pg_temp.refused(format($q$update signal_event set comment = 'changed' where signal_id = %L$q$, :'sig')) as r_upd \gset
select pg_temp.refused(format($q$delete from signal_event where signal_id = %L$q$, :'sig')) as r_del \gset
select pg_temp.sig_assert(:'r_upd' like '%append-only%' and :'r_del' like '%append-only%', 'signal_event is append-only');
update signal set stage = 'validation', validation_due = (now() at time zone 'Africa/Cairo')::date - 1 where id = :'sig';
select pg_temp.sig_assert((select overdue from v_signal_table where id = :'sig'), 'a signal past its due day is overdue');

-- The public key reads nothing and cannot call the step functions.
set role anon;
select pg_temp.refused(format($q$select signal_take_step(%L, 'note', 'validation', 'x')$q$, :'sig')) as r_anon \gset
select count(*) as anon_signals from signal \gset
reset role;
select pg_temp.sig_assert(:'r_anon' like '42501%' and :anon_signals = 0, 'the public key cannot read or step a signal');
