-- PHAROS CI — individual case reports (0059). Runs after every migration and the acceptance checks in ci.yml,
-- on the same database: the people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.

create function pg_temp.ci_assert(ok boolean, msg text) returns void language plpgsql as $$
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

insert into ingredient (id, inn_en) values ('00000000-0000-0000-0000-00000053a001', 'CI casoxicam');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-CI-N', 'XC', 'CI Caseland', 'CI Case Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-ci-lit', 'CI-CI-N', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true);
-- Flagged as the collector flags a case report (collectors/parsers/pubmed.py), as every such paper is.
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      structured) values
  ('00000000-0000-0000-0000-00000053b001', 'ci-ci-lit', '53001', 'https://pubmed.ncbi.nlm.nih.gov/53001/',
   'A case of hepatitis after CI casoxicam', 'en', 'literature', '2026-11-01', '2026-11-03 23:30+00',
   '{"pmid": "53001", "case_report": {"reason": "title"}}');
insert into issue (id, doc_type, title, anchor_document_id, first_date) values
  ('00000000-0000-0000-0000-00000053e001', 'literature', 'A case of hepatitis after CI casoxicam',
   '00000000-0000-0000-0000-00000053b001', '2026-11-01');
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000053e001', '00000000-0000-0000-0000-00000053b001', 'anchor', 'auto');
insert into issue_ingredient values ('00000000-0000-0000-0000-00000053e001', '00000000-0000-0000-0000-00000053a001');

\set sha '''aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'''

-- A reader cannot open a case, and nobody writes the table directly.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format($q$select create_upload_case('r.pdf', 'application/pdf', %L, 100, case_cairo_today())$q$, :sha)) as r_reader \gset
select pg_temp.refused($q$insert into safety_case (ref, origin, day_zero, document_id)
  values ('CASE-X', 'paper', current_date, '00000000-0000-0000-0000-00000053b001')$q$) as r_direct \gset
reset role;
select pg_temp.ci_assert(:'r_reader' like '42501%', 'a reader cannot open a case');
select pg_temp.ci_assert(:'r_direct' is not null and not exists (select 1 from safety_case where ref = 'CASE-X'),
  'nobody writes the case table directly');

-- A reviewer uploads a document; a file of another kind, a future day zero or a bad hash is refused.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format($q$select create_upload_case('x.exe', 'application/x-msdownload', %L, 100, case_cairo_today())$q$, :sha)) as r_mime \gset
select pg_temp.refused(format($q$select create_upload_case('r.pdf', 'application/pdf', %L, 100, case_cairo_today() + 1)$q$, :sha)) as r_future \gset
select pg_temp.refused($q$select create_upload_case('r.pdf', 'application/pdf', 'nothex', 100, case_cairo_today())$q$) as r_hash \gset
select create_upload_case('  Report from Dr Adel.pdf ', 'application/pdf', :sha, 2048, case_cairo_today() - 2) as up \gset
reset role;
select pg_temp.ci_assert(:'r_mime' like '%PHAROS reads PDF%', 'only the document kinds PHAROS reads are taken');
select pg_temp.ci_assert(:'r_future' like '%Day zero%', 'day zero cannot be in the future');
select pg_temp.ci_assert(:'r_hash' like '%SHA-256%', 'the file''s hash must be a SHA-256');
select pg_temp.ci_assert((select ref ~ '^CASE-\d{4}-\d{3}$' and status = 'queued' and file_name = 'Report from Dr Adel.pdf'
                                 and r2_key = 'sha256/aa/' || sha256
                                 and created_by = (select id from person where email = 'reviewer@example.test')
                            from safety_case where id = :'up'),
  'the case is numbered, queued for reading, and points at the archived file under its SHA-256');
select pg_temp.ci_assert((select due = case_cairo_today() - 2 + 15 and overdue = false from v_case_table where id = :'up'),
  'until seriousness is decided the case is due 15 days after day zero');

-- A case from a paper takes the paper's day zero and its one ingredient; a paper opens one case at most.
set role authenticated;
select create_paper_case('00000000-0000-0000-0000-00000053b001') as pc \gset
select pg_temp.refused($q$select create_paper_case('00000000-0000-0000-0000-00000053b001')$q$) as r_twice \gset
reset role;
select pg_temp.ci_assert((select origin = 'paper' and day_zero = '2026-11-04'
                                 and ingredient_id = '00000000-0000-0000-0000-00000053a001'
                                 and data ->> 'report_type' = 'literature'
                            from safety_case where id = :'pc'),
  'a paper''s case starts on the Cairo day PHAROS found it, with its ingredient');
select pg_temp.ci_assert(:'r_twice' like '%already has a case%', 'a paper opens one case at most');

-- The collector reads the document (as the database owner) and the form waits for a reviewer.
update safety_case set status = 'to_confirm', extracted = '{"reader": true}',
       data = '{"patient": {"initials": "A.M."}, "products": [{"name": "Casoxicam 8 mg", "role": "suspect"}]}',
       read_at = now(), updated_at = now()
 where id = :'up';
select updated_at as seen1 from safety_case where id = :'up' \gset

-- Confirming needs the four minimum criteria, the ingredient and the seriousness.
\set full '''{"patient": {"initials": "A.M.", "sex": "female"}, "reporter": {"qualification": "physician"}, "products": [{"name": "Casoxicam 8 mg", "role": "suspect"}], "reactions": [{"verbatim": "jaundice"}]}'''
set role authenticated;
select pg_temp.refused(format($q$select confirm_case(%L, %L, '{"patient": {"initials": "A.M."}, "products": [{"name": "Casoxicam 8 mg", "role": "suspect"}]}', true, '00000000-0000-0000-0000-00000053a001')$q$, :'up', :'seen1')) as r_invalid \gset
select pg_temp.refused(format($q$select confirm_case(%L, %L, %L, true, null)$q$, :'up', :'seen1', :full)) as r_noing \gset
select pg_temp.refused(format($q$select confirm_case(%L, %L, %L, null, '00000000-0000-0000-0000-00000053a001')$q$, :'up', :'seen1', :full)) as r_noserious \gset
select save_case(:'up', :'seen1', :full, false, '00000000-0000-0000-0000-00000053a001', 'Checked the narrative') as seen2 \gset
select pg_temp.refused(format($q$select confirm_case(%L, %L, %L, false, '00000000-0000-0000-0000-00000053a001')$q$, :'up', :'seen1', :full)) as r_stale \gset
select confirm_case(:'up', :'seen2', :full, false, '00000000-0000-0000-0000-00000053a001') as seen3 \gset
reset role;
select pg_temp.ci_assert(:'r_invalid' like '%Not a valid case yet: reporter, reaction missing%',
  'a case without a reporter and a reaction is not valid, and says what is missing');
select pg_temp.ci_assert(:'r_noing' like '%Choose the ingredient%', 'a confirmed case names its ingredient');
select pg_temp.ci_assert(:'r_noserious' like '%serious%', 'a confirmed case says whether it is serious');
select pg_temp.ci_assert(:'r_stale' like 'PH409 STALE_CASE%', 'a change made from an older view is refused as stale');
select pg_temp.ci_assert((select status = 'confirmed' and serious = false and confirmed_by is not null
                                 and case_missing(data) = '{}'::text[]
                            from safety_case where id = :'up')
                         and (select due = case_cairo_today() - 2 + 90 from v_case_table where id = :'up'),
  'a confirmed non-serious case is due 90 days after day zero');

-- The E2B file is asked for from the confirmed form; sent needs a day and a reference.
set role authenticated;
select ask_case_e2b(:'up', :'seen3') as seen4 \gset
select pg_temp.refused(format($q$select ask_case_e2b(%L, %L)$q$, :'up', :'seen4')) as r_e2b_twice \gset
select pg_temp.refused(format($q$select case_sent(%L, %L, case_cairo_today(), '  ')$q$, :'up', :'seen4')) as r_noref \gset
select case_sent(:'up', :'seen4', case_cairo_today(), 'EDA-ICSR-2026-77') as seen5 \gset
select pg_temp.refused(format($q$select save_case(%L, %L, '{}', true, null)$q$, :'up', :'seen5')) as r_sent_edit \gset
select reopen_case(:'up', :'seen5', 'Follow-up from the physician', case_cairo_today()) as seen6 \gset
reset role;
select pg_temp.ci_assert(:'r_e2b_twice' like '%already being made%', 'the E2B file is asked for once at a time');
select pg_temp.ci_assert(:'r_noref' like '%reference%', 'a case sent to the authority keeps its reference');
select pg_temp.ci_assert(:'r_sent_edit' like '%Reopen it first%', 'a sent case is reopened before it changes');
select pg_temp.ci_assert((select status = 'to_confirm' and day_zero = case_cairo_today() and sent_on is not null
                            from safety_case where id = :'up'),
  'a follow-up reopens the case with a new day zero');
select pg_temp.ci_assert((select array_agg(step::text order by created_at, id) from case_event where case_id = :'up')
    = array['received','saved','confirmed','e2b_asked','sent','reopened'],
  'every step is recorded once, in order');
select pg_temp.ci_assert((select data -> 'reactions' -> 0 ->> 'verbatim' = 'jaundice' from case_event
                           where case_id = :'up' and step = 'confirmed'),
  'the confirmed form is kept in the history');

-- The history is append-only, and the public key reads nothing.
select pg_temp.refused(format($q$update case_event set comment = 'changed' where case_id = %L$q$, :'up')) as r_upd \gset
select pg_temp.refused(format($q$delete from case_event where case_id = %L$q$, :'up')) as r_del \gset
select pg_temp.ci_assert(:'r_upd' like '%append-only%' and :'r_del' like '%append-only%', 'case_event is append-only');
set role anon;
select count(*) as anon_cases from safety_case \gset
select pg_temp.refused(format($q$select case_note(%L, 'x')$q$, :'up')) as r_anon \gset
reset role;
select pg_temp.ci_assert(:anon_cases = 0 and :'r_anon' like '42501%', 'the public key cannot read or change a case');
