-- PHAROS CI — inspection evidence (0046, 0047): the weekly report is signed, and the audit log never changes.
-- Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist. Everything
-- here is rolled back at the end (a signature cannot be removed, so the test leaves none behind).

begin;

create function pg_temp.sw_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.sw_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- Claims for a person, with a password sign-in this many seconds ago (null: no password sign-in at all).
create function pg_temp.sw_as(p uuid, ago int) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object(
    'sub', p, 'role', 'authenticated',
    'amr', case when ago is null then '[{"method":"otp","timestamp":0}]'::jsonb
                else jsonb_build_array(jsonb_build_object('method', 'password',
                       'timestamp', extract(epoch from now())::bigint - ago)) end)::text, false)
$$;

insert into weekly_report (id, week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
  values ('00000000-0000-0000-0000-00000005f001', '2019-01-06', '2019-01-12',
          'reports/weekly/2019-01-06/PHAROS-weekly-2019-01-06.xlsx',
          '1111111111111111111111111111111111111111111111111111111111111111',
          'reports/weekly/2019-01-06/PHAROS-weekly-2019-01-06.pdf',
          '2222222222222222222222222222222222222222222222222222222222222222');
select encode(sha256(convert_to(
  '2222222222222222222222222222222222222222222222222222222222222222:1111111111111111111111111111111111111111111111111111111111111111',
  'UTF8')), 'hex') as sw_expected \gset

-- The administrator approves the week with a password typed a minute ago; the reviewer reviews it.
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000a1', 60);
set role authenticated;
select sign_record('weekly_report', '00000000-0000-0000-0000-00000005f001', 'approved', ' Read in full ') as sw_admin \gset
select record_fingerprint('weekly_report', '00000000-0000-0000-0000-00000005f001') as sw_fp1 \gset
select pg_temp.sw_refused($q$select sign_record('weekly_report', '00000000-0000-0000-0000-00000005f001', 'approved')$q$) as sw_twice \gset
reset role;
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000c3', 30);
set role authenticated;
select sign_record('weekly_report', '00000000-0000-0000-0000-00000005f001', 'reviewed') is not null as sw_reviewer \gset
select record_fingerprint('weekly_report', '00000000-0000-0000-0000-00000005f001') as sw_fp2 \gset
reset role;

-- The reviewer without a fresh password; a reader at all; a pack that was never made.
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000c3', 600);
set role authenticated;
select pg_temp.sw_refused($q$select sign_record('weekly_report', '00000000-0000-0000-0000-00000005f001', 'approved')$q$) as sw_old \gset
reset role;
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000b2', 30);
set role authenticated;
select pg_temp.sw_refused($q$select sign_record('weekly_report', '00000000-0000-0000-0000-00000005f001', 'reviewed')$q$) as sw_reader \gset
select count(*) as sw_reader_sees from sign_off where record_id = '00000000-0000-0000-0000-00000005f001' \gset
reset role;
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000a1', 30);
set role authenticated;
select pg_temp.sw_refused($q$select sign_record('pack', '00000000-0000-0000-0000-00000005f002', 'approved')$q$) as sw_pack \gset
reset role;

select signed_name as sw_name, signed_role as sw_role, comment as sw_comment, record_sha256 as sw_sha
  from sign_off where id = :'sw_admin' \gset

-- The week made again: a new PDF no longer matches the signatures.
update weekly_report set pdf_sha256 = '3333333333333333333333333333333333333333333333333333333333333333'
 where id = '00000000-0000-0000-0000-00000005f001';
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000b2', null);
set role authenticated;
select record_fingerprint('weekly_report', '00000000-0000-0000-0000-00000005f001') as sw_fp3 \gset
reset role;
select set_config('request.jwt.claims', '', false);

-- ───────────── the audit log is never changed or removed ─────────────
select count(*) as sw_audited from audit_log
 where table_name = 'sign_off' and action = 'INSERT' and new_row ->> 'record_id' = '00000000-0000-0000-0000-00000005f001' \gset
select max(id) as sw_last from audit_log \gset
-- As the database owner (CI connects as postgres, the owner of every table).
select pg_temp.sw_refused(format('update audit_log set action = %L where id = %s', 'X', :sw_last)) as sw_owner_upd \gset
select pg_temp.sw_refused(format('delete from audit_log where id = %s', :sw_last)) as sw_owner_del \gset
select pg_temp.sw_refused('truncate audit_log') as sw_owner_trunc \gset
-- As the service key and as a signed-in administrator.
set role service_role;
select pg_temp.sw_refused(format('delete from audit_log where id = %s', :sw_last)) as sw_service_del \gset
select pg_temp.sw_refused(format('update audit_log set action = %L where id = %s', 'X', :sw_last)) as sw_service_upd \gset
reset role;
select pg_temp.sw_as('00000000-0000-0000-0000-0000000000a1', 30);
set role authenticated;
select pg_temp.sw_refused(format('delete from audit_log where id = %s', :sw_last)) as sw_admin_del \gset
select pg_temp.sw_refused(format('update audit_log set action = %L where id = %s', 'X', :sw_last)) as sw_admin_upd \gset
reset role;
select set_config('request.jwt.claims', '', false);
select (select action from audit_log where id = :sw_last) as sw_action_now \gset

select pg_temp.sw_assert(:'sw_name' = 'CI Admin' and :'sw_role' = 'admin' and :'sw_comment' = 'Read in full'
    and :'sw_sha' = :'sw_expected' and :'sw_fp1' = :'sw_expected',
  'the signature carries the name, role, comment and the SHA-256 of the week''s PDF and Excel file');
select pg_temp.sw_assert(:'sw_fp2' = :'sw_fp1' and :'sw_reviewer' = 't',
  'a reviewer signs the weekly report too, and the fingerprint of an unchanged report stays the same');
select pg_temp.sw_assert(:'sw_twice' like '23505%', 'the same person cannot sign the same week twice with one meaning');
select pg_temp.sw_assert(:'sw_old' like '28P01%', 'a password older than five minutes cannot sign');
select pg_temp.sw_assert(:'sw_reader' like '42501%' and :sw_reader_sees = 2,
  'a reader signs nothing and reads every signature');
select pg_temp.sw_assert(:'sw_pack' like '22023%', 'a pack that was never made cannot be signed (0048)');
select pg_temp.sw_assert(:'sw_fp3' <> :'sw_sha', 'a week made again no longer matches its signatures');
select pg_temp.sw_assert(:sw_audited = 2, 'each signature is in the audit log');
select pg_temp.sw_assert(:'sw_owner_upd' like '%never changed or removed%'
    and :'sw_owner_del' like '%never changed or removed%'
    and :'sw_owner_trunc' like '%never changed or removed%',
  'the audit log refuses an update, a delete and a truncate even from the database owner');
select pg_temp.sw_assert(:'sw_service_del' like '42501%' and :'sw_service_upd' like '42501%'
    and :'sw_admin_del' like '42501%' and :'sw_admin_upd' like '42501%' and :'sw_action_now' <> 'X',
  'neither the service key nor an administrator can change or remove an audit row');
select pg_temp.sw_assert(
  not has_table_privilege('service_role', 'public.audit_log', 'update')
    and not has_table_privilege('service_role', 'public.audit_log', 'delete')
    and not has_table_privilege('service_role', 'public.audit_log', 'truncate')
    and not has_table_privilege('authenticated', 'public.audit_log', 'update')
    and not has_table_privilege('authenticated', 'public.audit_log', 'delete')
    and not has_table_privilege('anon', 'public.audit_log', 'truncate'),
  'nobody holds the right to update, delete or truncate the audit log');

rollback;
