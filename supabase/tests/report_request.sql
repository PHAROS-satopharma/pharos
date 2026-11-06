-- PHAROS CI — packs on request (0048): report_request, request_report(), the fingerprint of a pack and its
-- signature; inspection packs for administrators only; at most two waiting per person and five in all. Runs on the database ci.yml prepared: CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.
-- Everything here is rolled back at the end (a signature and an audit row cannot be removed).

begin;

create function pg_temp.rr_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.rr_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- Claims for a person, with a password sign-in this many seconds ago.
create function pg_temp.rr_as(p uuid, ago int) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object(
    'sub', p, 'role', 'authenticated',
    'amr', jsonb_build_array(jsonb_build_object('method', 'password',
             'timestamp', extract(epoch from now())::bigint - ago)))::text, false)
$$;

insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000048a001', 'CI packamine', 'Z98ZZ01');
select signal_cairo_today() as rr_today \gset

-- ───────────── a reviewer asks; the same pack asked again is the same request ─────────────
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000c3', 60);
set role authenticated;
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-12-02', :'rr_today') as rr_psur \gset
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-12-02', :'rr_today') as rr_psur_again \gset
-- an inspection pack is for administrators only
select pg_temp.rr_refused(format('select request_report(%L, null, %L, %L)', 'inspection',
  (:'rr_today'::date - 364)::text, :'rr_today')) as rr_rev_insp \gset
-- a second pack of hers waits; a third is refused until one is ready
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2025-01-01', '2025-12-31') as rr_psur2 \gset
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2025-01-01', '2025-12-31') as rr_psur2_again \gset
select pg_temp.rr_refused($q$select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-01-01', '2024-12-31')$q$) as rr_third \gset
select pg_temp.rr_refused($q$select request_report('psur', null, '2026-01-01', '2026-06-30')$q$) as rr_psur_none \gset
select pg_temp.rr_refused($q$select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2020-01-01', '2025-01-02')$q$) as rr_long \gset
select pg_temp.rr_refused($q$select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2026-06-30', '2026-01-01')$q$) as rr_back \gset
select pg_temp.rr_refused($q$select request_report('monthly', null, '2026-01-01', '2026-06-30')$q$) as rr_kind \gset
select pg_temp.rr_refused($q$select request_report('psur', '00000000-0000-0000-0000-00000048afff', '2026-01-01', '2026-06-30')$q$) as rr_unknown \gset
select pg_temp.rr_refused(format('select request_report(%L, %L, %L, %L)', 'psur', '00000000-0000-0000-0000-00000048a001',
  (:'rr_today'::date + 1)::text, (:'rr_today'::date + 30)::text)) as rr_future \gset
-- no direct write from the app, even for a reviewer
select pg_temp.rr_refused($q$insert into report_request (kind, from_day, to_day, requested_by)
  values ('inspection', '2026-01-01', '2026-06-30', '00000000-0000-0000-0000-0000000000c3')$q$) as rr_insert \gset
select pg_temp.rr_refused(format('update report_request set status = %L where id = %L', 'done', :'rr_psur')) as rr_update \gset
reset role;

-- An administrator asking for the same pack gets the same request; an administrator asks for an inspection pack.
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000a1', 60);
set role authenticated;
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-12-02', :'rr_today') as rr_psur_admin \gset
select request_report('inspection', null, (:'rr_today'::date - 364), :'rr_today') as rr_insp \gset
select pg_temp.rr_refused($q$select request_report('inspection', '00000000-0000-0000-0000-00000048a001', '2026-01-01', '2026-06-30')$q$) as rr_insp_ing \gset
select count(*) as rr_admin_sees from report_request where id in (:'rr_psur', :'rr_insp') \gset
reset role;

-- The reviewer sees the PSUR packs and no inspection pack.
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000c3', 60);
set role authenticated;
select count(*) as rr_rev_sees_insp from report_request where kind = 'inspection' \gset
select count(*) as rr_rev_sees_psur from report_request where id = :'rr_psur' \gset
reset role;

-- Five waiting in all (the collector's connection fills up the rest): nobody asks for a sixth.
insert into report_request (kind, ingredient_id, from_day, to_day, requested_by)
select 'psur', '00000000-0000-0000-0000-00000048a001', '2010-01-01'::date + g, '2010-01-01'::date + g,
       (select id from person where auth_user_id = '00000000-0000-0000-0000-0000000000b2')
  from generate_series(1, 5 - (select count(*)::int from report_request where status in ('queued', 'building'))) g;
select count(*) as rr_waiting_all from report_request where status in ('queued', 'building') \gset
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000a1', 60);
set role authenticated;
select pg_temp.rr_refused($q$select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2023-01-01', '2023-12-31')$q$) as rr_sixth \gset
-- the same pack again is still the one request, not a new one
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-12-02', :'rr_today') as rr_psur_full \gset
reset role;
update report_request set status = 'failed', error = 'CI filler'
 where from_day < '2011-01-01' and status = 'queued' and ingredient_id = '00000000-0000-0000-0000-00000048a001';

-- A reader reads the requests and asks for none.
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000b2', 60);
set role authenticated;
select pg_temp.rr_refused(format('select request_report(%L, null, %L, %L)', 'inspection', '2026-01-01', '2026-06-30')) as rr_reader \gset
select count(*) as rr_reader_sees from report_request where id in (:'rr_psur', :'rr_insp') \gset
select count(*) as rr_reader_sees_insp from report_request where kind = 'inspection' \gset
reset role;
select set_config('request.jwt.claims', '', false);
set role anon;
select pg_temp.rr_refused('select count(*) from report_request') as rr_anon_read \gset
select pg_temp.rr_refused(format('select request_report(%L, null, %L, %L)', 'inspection', '2026-01-01', '2026-06-30')) as rr_anon_ask \gset
reset role;

select status as rr_status, requested_by::text as rr_by, attempts as rr_attempts
  from report_request where id = :'rr_psur' \gset
select count(*) as rr_audited from audit_log
 where table_name = 'report_request' and action = 'INSERT' and row_pk in (:'rr_psur', :'rr_insp') \gset

-- ───────────── not made yet: nothing to sign ─────────────
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000a1', 30);
set role authenticated;
select record_fingerprint('pack', :'rr_psur') is null as rr_fp_none \gset
select pg_temp.rr_refused(format('select sign_record(%L, %L, %L)', 'pack', :'rr_psur', 'approved')) as rr_sign_early \gset
reset role;

-- ───────────── the collector makes it (direct connection, the owner) ─────────────
update report_request set status = 'building', attempts = attempts + 1, started_at = now() where id = :'rr_psur';
select pg_temp.rr_refused(format('update report_request set status = %L where id = %L', 'done', :'rr_psur')) as rr_done_no_files \gset
update report_request
   set status = 'done', made_at = now(), git_sha = 'abc123',
       pdf_r2_key = 'reports/packs/psur/' || id || '/PHAROS-PSUR-pack.pdf',
       pdf_sha256 = '4444444444444444444444444444444444444444444444444444444444444444',
       xlsx_r2_key = 'reports/packs/psur/' || id || '/PHAROS-PSUR-pack.xlsx',
       xlsx_sha256 = '5555555555555555555555555555555555555555555555555555555555555555'
 where id = :'rr_psur';
select encode(sha256(convert_to(
  '4444444444444444444444444444444444444444444444444444444444444444:5555555555555555555555555555555555555555555555555555555555555555',
  'UTF8')), 'hex') as rr_expected \gset

update report_request
   set status = 'done', made_at = now(), git_sha = 'abc123',
       pdf_r2_key = 'reports/packs/inspection/' || id || '/PHAROS-inspection.pdf',
       pdf_sha256 = '7777777777777777777777777777777777777777777777777777777777777777',
       xlsx_r2_key = 'reports/packs/inspection/' || id || '/PHAROS-inspection.xlsx',
       xlsx_sha256 = '8888888888888888888888888888888888888888888888888888888888888888'
 where id = :'rr_insp';
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000c3', 30);
set role authenticated;
select record_fingerprint('pack', :'rr_insp') is null as rr_rev_insp_fp \gset
select pg_temp.rr_refused(format('select sign_record(%L, %L, %L)', 'pack', :'rr_insp', 'reviewed')) as rr_rev_insp_sign \gset
reset role;
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000a1', 30);
set role authenticated;
select record_fingerprint('pack', :'rr_insp') is not null as rr_admin_insp_fp \gset
reset role;

-- Once made, the same pack can be asked for again: a new request.
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000c3', 60);
set role authenticated;
select request_report('psur', '00000000-0000-0000-0000-00000048a001', '2024-12-02', :'rr_today') as rr_psur_new \gset
reset role;

-- The reviewer and the administrator sign the pack that was made.
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000c3', 30);
set role authenticated;
select record_fingerprint('pack', :'rr_psur') as rr_fp \gset
select sign_record('pack', :'rr_psur', 'reviewed', 'Read for the PSUR') as rr_sig_rev \gset
reset role;
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000a1', 30);
set role authenticated;
select sign_record('pack', :'rr_psur', 'approved') is not null as rr_sig_admin \gset
reset role;
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000b2', 30);
set role authenticated;
select pg_temp.rr_refused(format('select sign_record(%L, %L, %L)', 'pack', :'rr_psur', 'reviewed')) as rr_sig_reader \gset
reset role;
select record_sha256 as rr_signed_sha, signed_role as rr_signed_role from sign_off where id = :'rr_sig_rev' \gset

-- A file changed afterwards no longer matches the signatures.
update report_request set pdf_sha256 = '6666666666666666666666666666666666666666666666666666666666666666'
 where id = :'rr_psur';
select pg_temp.rr_as('00000000-0000-0000-0000-0000000000b2', 30);
set role authenticated;
select record_fingerprint('pack', :'rr_psur') as rr_fp_changed \gset
reset role;
select set_config('request.jwt.claims', '', false);

select pg_temp.rr_assert(:'rr_psur' is not null and :'rr_psur_again' = :'rr_psur' and :'rr_psur_admin' = :'rr_psur',
  'the same pack asked for again, by anyone, while it waits is the same request');
select pg_temp.rr_assert(:'rr_insp' is not null and :'rr_insp' <> :'rr_psur', 'an inspection pack is its own request');
select pg_temp.rr_assert(:'rr_rev_insp' like '42501%', 'a reviewer cannot ask for an inspection pack');
select pg_temp.rr_assert(:rr_admin_sees = 2 and :rr_rev_sees_insp = 0 and :rr_rev_sees_psur = 1
    and :rr_reader_sees_insp = 0,
  'an administrator sees the inspection pack; a reviewer and a reader see the PSUR packs only');
select pg_temp.rr_assert(:'rr_rev_insp_fp' = 't' and :'rr_rev_insp_sign' like '22023%' and :'rr_admin_insp_fp' = 't',
  'a reviewer neither reads the fingerprint of an inspection pack nor signs it; an administrator does');
select pg_temp.rr_assert(:'rr_psur2' is not null and :'rr_psur2_again' = :'rr_psur2'
    and :'rr_third' like '22023%Two packs of yours are already waiting%',
  'two packs of one person wait at once; the third is refused until one is ready');
select pg_temp.rr_assert(:rr_waiting_all = 5 and :'rr_sixth' like '22023%' and :'rr_psur_full' = :'rr_psur',
  'five packs wait at most in all; the same pack asked again is still its one request');
select pg_temp.rr_assert(:'rr_status' = 'queued' and :'rr_by' = (select id::text from person where auth_user_id = '00000000-0000-0000-0000-0000000000c3')
    and :rr_attempts = 0,
  'a request waits as queued, under the person who asked');
select pg_temp.rr_assert(:'rr_insp_ing' like '22023%' and :'rr_psur_none' like '22023%' and :'rr_kind' like '22023%'
    and :'rr_back' like '22023%' and :'rr_unknown' like 'P0002%' and :'rr_future' like '22023%',
  'an inspection pack has no ingredient, a PSUR pack has one that exists, the days run forward and have started');
select pg_temp.rr_assert(:'rr_long' like '22023%five years%', 'more than five years is refused');
select pg_temp.rr_assert(:'rr_insert' like '42501%' and :'rr_update' like '42501%',
  'the app writes no request directly, not even a reviewer');
select pg_temp.rr_assert(:'rr_reader' like '42501%' and :rr_reader_sees = 1,
  'a reader reads the requests and cannot ask for a pack');
select pg_temp.rr_assert(:'rr_anon_read' like '42501%' and :'rr_anon_ask' like '42501%',
  'a signed-out visitor reads nothing and asks for nothing');
select pg_temp.rr_assert(:rr_audited = 2, 'every request is in the audit log');
select pg_temp.rr_assert(:'rr_fp_none' = 't' and :'rr_sign_early' like '22023%',
  'a pack not made yet has no fingerprint and cannot be signed');
select pg_temp.rr_assert(:'rr_done_no_files' like '23514%', 'a request is done only with both files and their SHA-256');
select pg_temp.rr_assert(:'rr_psur_new' is not null and :'rr_psur_new' <> :'rr_psur',
  'a pack already made can be asked for again');
select pg_temp.rr_assert(:'rr_fp' = :'rr_expected' and :'rr_signed_sha' = :'rr_expected' and :'rr_signed_role' = 'reviewer'
    and :'rr_sig_admin' = 't',
  'the fingerprint of a pack is the SHA-256 of its PDF and Excel hashes; a reviewer and an administrator sign it');
select pg_temp.rr_assert(:'rr_sig_reader' like '42501%', 'a reader signs no pack');
select pg_temp.rr_assert(:'rr_fp_changed' <> :'rr_expected', 'a pack whose file changed no longer matches its signatures');
select pg_temp.rr_assert(
  not has_table_privilege('service_role', 'public.report_request', 'select')
    and not has_table_privilege('service_role', 'public.report_request', 'insert')
    and not has_table_privilege('authenticated', 'public.report_request', 'insert')
    and not has_table_privilege('authenticated', 'public.report_request', 'update')
    and not has_table_privilege('authenticated', 'public.report_request', 'delete')
    and not has_function_privilege('anon', 'public.request_report(text, uuid, date, date)', 'execute')
    and not has_function_privilege('service_role', 'public.request_report(text, uuid, date, date)', 'execute'),
  'only request_report() writes a request; the service key holds no right on them');

rollback;
