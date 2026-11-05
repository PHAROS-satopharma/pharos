-- PHAROS CI — electronic sign-off (0030). Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader
-- (…b2) and CI Reviewer (…c3) exist.

create function pg_temp.so_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.so_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- Claims for a person, with a password sign-in this many seconds ago (null: no password sign-in at all).
create function pg_temp.so_as(p uuid, ago int) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object(
    'sub', p, 'role', 'authenticated',
    'amr', case when ago is null then '[{"method":"otp","timestamp":0}]'::jsonb
                else jsonb_build_array(jsonb_build_object('method', 'password',
                       'timestamp', extract(epoch from now())::bigint - ago)) end)::text, false)
$$;

insert into monthly_report (id, month, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('00000000-0000-0000-0000-00000005e001', '2024-01-01', 'raw/x', 'aa', 'raw/p', 'bb');
insert into signal (id, ref, title, opened_by, validation_due, stage, outcome, closed_at) values
  ('00000000-0000-0000-0000-00000005e002', 'SIG-CI-SIGN', 'Closed signal', (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000a1'),
   '2025-01-01', 'closed', 'refuted', '2025-01-02 10:00+00');
insert into signal (id, ref, title, opened_by, validation_due) values
  ('00000000-0000-0000-0000-00000005e003', 'SIG-CI-OPEN', 'Open signal', (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000a1'),
   '2025-01-01');

-- The admin signs the report with a password entered a minute ago.
select pg_temp.so_as('00000000-0000-0000-0000-0000000000a1', 60);
set role authenticated;
select sign_record('monthly_report', '00000000-0000-0000-0000-00000005e001', 'approved', '  Checked against the log  ') as so_id \gset
select pg_temp.so_refused($q$select sign_record('monthly_report', '00000000-0000-0000-0000-00000005e001', 'approved')$q$) as so_twice \gset
select record_fingerprint('monthly_report', '00000000-0000-0000-0000-00000005e001') as so_fp \gset
select pg_temp.so_refused($q$update sign_off set meaning = 'reviewed'$q$) as so_upd \gset
reset role;
select signed_name as so_name, signed_role as so_role, comment as so_comment, record_sha256 as so_sha
  from sign_off where id = :'so_id' \gset

-- Without a fresh password: an old sign-in, or a sign-in by e-mail code.
select pg_temp.so_as('00000000-0000-0000-0000-0000000000a1', 600);
set role authenticated;
select pg_temp.so_refused($q$select sign_record('monthly_report', '00000000-0000-0000-0000-00000005e001', 'reviewed')$q$) as so_old \gset
reset role;
select pg_temp.so_as('00000000-0000-0000-0000-0000000000a1', null);
set role authenticated;
select pg_temp.so_refused($q$select sign_record('monthly_report', '00000000-0000-0000-0000-00000005e001', 'reviewed')$q$) as so_otp \gset
reset role;

-- A reviewer signs a closed signal, not an open one, and not the monthly report; a reader signs nothing.
select pg_temp.so_as('00000000-0000-0000-0000-0000000000c3', 30);
set role authenticated;
select pg_temp.so_refused($q$select sign_record('monthly_report', '00000000-0000-0000-0000-00000005e001', 'reviewed')$q$) as so_rev_report \gset
select pg_temp.so_refused($q$select sign_record('signal', '00000000-0000-0000-0000-00000005e003', 'reviewed')$q$) as so_open \gset
select sign_record('signal', '00000000-0000-0000-0000-00000005e002', 'reviewed') is not null as so_sig \gset
reset role;
select pg_temp.so_as('00000000-0000-0000-0000-0000000000b2', 30);
set role authenticated;
select pg_temp.so_refused($q$select sign_record('signal', '00000000-0000-0000-0000-00000005e002', 'reviewed')$q$) as so_reader \gset
select count(*) as so_seen from sign_off where record_id in ('00000000-0000-0000-0000-00000005e001', '00000000-0000-0000-0000-00000005e002') \gset
reset role;

-- A report made again no longer matches the signature.
update monthly_report set pdf_sha256 = 'cc' where id = '00000000-0000-0000-0000-00000005e001';
select pg_temp.so_as('00000000-0000-0000-0000-0000000000b2', null);
set role authenticated;
select record_fingerprint('monthly_report', '00000000-0000-0000-0000-00000005e001') as so_fp2 \gset
reset role;
select pg_temp.so_refused($q$delete from sign_off$q$) as so_del \gset

select pg_temp.so_assert(:'so_name' = 'CI Admin' and :'so_role' = 'admin' and :'so_comment' = 'Checked against the log'
  and :'so_sha' = :'so_fp', 'the signature carries the name, role, comment and the record''s fingerprint');
select pg_temp.so_assert(:'so_twice' like '23505%', 'the same person cannot sign the same record twice with one meaning');
select pg_temp.so_assert(:'so_upd' like '42501%' and :'so_del' like '%never changed or removed%',
  'a signature is never changed or removed, not even by the database owner');
select pg_temp.so_assert(:'so_old' like '28P01%' and :'so_otp' like '28P01%',
  'a password older than five minutes, or no password at all, cannot sign');
select pg_temp.so_assert(:'so_rev_report' like '42501%', 'only an administrator signs the monthly report');
select pg_temp.so_assert(:'so_open' like '%once it is closed%' and :so_sig, 'a reviewer signs a closed signal only');
select pg_temp.so_assert(:'so_reader' like '42501%' and :so_seen = 2, 'a reader signs nothing and reads every signature');
select pg_temp.so_assert(:'so_fp2' <> :'so_fp', 'a report made again no longer matches its signature');

-- The signatures stay (they cannot be removed); the records they name go.
delete from signal where id in ('00000000-0000-0000-0000-00000005e002', '00000000-0000-0000-0000-00000005e003');
delete from monthly_report where id = '00000000-0000-0000-0000-00000005e001';
