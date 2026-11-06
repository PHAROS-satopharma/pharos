-- PHAROS CI — the Ingredients screen (0039): one ingredient across every source. Runs on the database ci.yml
-- prepared: CI Admin (…a1) and CI Reader (…b2) exist. Everything here happens in one transaction that is
-- rolled back at the end, so nothing is left behind (review_event cannot be deleted).

begin;

create function pg_temp.is_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.is_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- ───────────── the ingredient, its class and their words ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000037a001', 'CI screenamine', 'Z99ZZ01'),
  ('00000000-0000-0000-0000-00000037a002', 'CI otheramine', 'Z99ZZ02');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-00000037c001', '00000000-0000-0000-0000-00000037a001', 'en', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037c002', '00000000-0000-0000-0000-00000037a001', 'de', 'CI Screenamin'),
  ('00000000-0000-0000-0000-00000037c003', '00000000-0000-0000-0000-00000037a002', 'en', 'CI otheramine');
-- d001 is the ingredient's group (searched); d002 its parent class, shown but not searched (0049).
insert into drug_class (id, code, name_en, origin) values
  ('00000000-0000-0000-0000-00000037d001', 'Z99ZZ', 'CI screenoids', 'atc'),
  ('00000000-0000-0000-0000-00000037d002', 'Z99Z', 'CI zparentoids', 'atc');
insert into class_term (id, class_id, lang, term) values
  ('00000000-0000-0000-0000-00000037d101', '00000000-0000-0000-0000-00000037d001', 'en', 'ci screenoids'),
  ('00000000-0000-0000-0000-00000037d102', '00000000-0000-0000-0000-00000037d001', 'de', 'CI-Screenoide'),
  ('00000000-0000-0000-0000-00000037d201', '00000000-0000-0000-0000-00000037d002', 'en', 'ci zparentoids');
insert into ingredient_class (ingredient_id, class_id, relation, enabled) values
  ('00000000-0000-0000-0000-00000037a001', '00000000-0000-0000-0000-00000037d001', 'group', true),
  ('00000000-0000-0000-0000-00000037a001', '00000000-0000-0000-0000-00000037d002', 'parent', false);

-- ───────────── authorities: four of hers, one country with two authorities, one other, one library ─────────────
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-IS-A', 'XS', 'CI Screenland', 'CI Screenland Agency', '{en}', 'https://screen.example.test/'),
  ('CI-IS-B', 'XS', 'CI Screenland', 'CI Screenland Institute', '{en}', null),
  ('CI-IS-C', 'XQ', 'CI Quietland', 'CI Quietland Agency', '{en}', null),
  ('CI-IS-D', 'XF', 'CI Failland', 'CI Failland Agency', '{en}', null),
  ('CI-IS-E', 'XU', 'CI Unreadland', 'CI Unreadland Agency', '{en}', null),
  ('CI-IS-F', 'XO', 'CI Otherland', 'CI Otherland Agency', '{en}', null),
  ('CI-IS-N', 'XN', 'CI Paperland', 'CI Library', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-is-a-feed', 'CI-IS-A', 'safety', 'rss', 'https://screen.example.test/feed.xml', 'feed', '{en}',
   'https://screen.example.test/safety', true),
  ('ci-is-a-mail', 'CI-IS-A', 'safety', 'email', 'https://screen.example.test/news', 'email_inbox', '{en}',
   'https://screen.example.test/news', true),
  ('ci-is-a-spc', 'CI-IS-A', 'spc', 'api', 'https://screen.example.test/spc.json', 'ci', '{en}',
   'https://screen.example.test/products', true),
  ('ci-is-b-html', 'CI-IS-B', 'safety', 'html', 'https://institute.example.test/letters', 'generic_html', '{en}',
   null, true),
  ('ci-is-c-html', 'CI-IS-C', 'safety', 'html', 'https://quiet.example.test/dhpc', 'generic_html', '{en}', null, true),
  ('ci-is-d-html', 'CI-IS-D', 'safety', 'html', 'https://fail.example.test/alerts', 'generic_html', '{en}', null, true),
  ('ci-is-e-off', 'CI-IS-E', 'safety', 'html', 'https://unread.example.test/safety', 'generic_html', '{en}', null,
   false),
  ('ci-is-f-fda', 'CI-IS-F', 'recall', 'api', 'https://api.fda.gov/drug/enforcement.json', 'openfda_enforcement',
   '{en}', 'https://www.accessdata.fda.gov/scripts/ires/index.cfm', true),
  ('ci-is-lit', 'CI-IS-N', 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}',
   'https://pubmed.example.test/', true);
insert into regulator_page (regulator_id, kind, sort, label, url, read_by, note) values
  ('CI-IS-A', 'safety', 1, 'CI Screenland safety page', 'https://screen.example.test/safety', '{ci-is-a-feed}', null),
  ('CI-IS-C', 'database', 1, 'CI Quietland database', 'https://quiet.example.test/db', '{}', null),
  ('CI-IS-C', 'dhpc', 2, 'CI Quietland DHPC', 'https://quiet.example.test/dhpc', '{ci-is-c-html}', null),
  ('CI-IS-D', 'safety', 1, 'CI Failland alerts', 'https://fail.example.test/alerts', '{ci-is-d-html}', null),
  ('CI-IS-E', 'safety', 1, 'CI Unreadland safety', 'https://unread.example.test/safety', '{ci-is-e-off}',
   'CI: the site refuses automated reading.');

-- ───────────── reads: the week is Sunday 1 Nov 00:00 to Saturday 7 Nov 24:00, Cairo (UTC+2) ─────────────
insert into run (id, trigger) values ('00000000-0000-0000-0000-00000037f001', 'backfill');
insert into source_run (run_id, source_id, started_at, error) values
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-a-feed', '2026-10-31 21:00+00', null),   -- Saturday 23:00
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-a-feed', '2026-11-02 08:00+00', null),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-a-spc', '2026-11-02 09:00+00', 'no label read: CI'),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-c-html', '2026-11-02 08:00+00', null),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-c-html', '2026-11-03 08:00+00', null),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-c-html', '2026-11-04 08:00+00', 'time budget reached: CI'),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-d-html', '2026-11-02 08:00+00', null),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-d-html', '2026-11-03 08:00+00', 'HTTP 500 from fail.example.test'),
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-f-fda', '2026-11-07 21:59+00', null),       -- Saturday 23:59
  ('00000000-0000-0000-0000-00000037f001', 'ci-is-lit', '2026-11-02 08:00+00', null);

-- ───────────── notices and papers ─────────────
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill, structured) values
  ('00000000-0000-0000-0000-00000037b001', 'ci-is-a-feed', 'h1', 'https://screen.example.test/item-1',
   'CI screenamine: new warning', 'en', 'dhpc', '2026-11-03', '2026-11-03 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000037b002', 'ci-is-a-feed', 'h2', 'https://screen.example.test/feed.xml?id=2',
   'Die CI-Screenoide: Klassenwarnung', 'de', 'safety_update', null, '2026-11-07 21:30+00', false, null),
  ('00000000-0000-0000-0000-00000037b003', 'ci-is-a-mail', 'email:00000000-0000-0000-0000-00000037e0e1',
   'email:00000000-0000-0000-0000-00000037e0e1', 'A bulletin about CI screenamine', 'en', 'newsletter',
   '2026-11-04', '2026-11-04 08:00+00', false,
   '{"inbound_email_id":"00000000-0000-0000-0000-00000037e0e1","raw_r2_key":"inbound/2026-11-04/ci-is.eml"}'),
  ('00000000-0000-0000-0000-00000037b004', 'ci-is-a-feed', 'h4', 'https://screen.example.test/item-4',
   'CI screenamine, the week before', 'en', 'dhpc', '2026-10-30', '2026-10-30 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000037b005', 'ci-is-a-feed', 'h5', 'https://screen.example.test/item-5',
   'CI screenamine, from a backfill', 'en', 'dhpc', '2026-11-02', '2026-11-02 08:00+00', true, null),
  ('00000000-0000-0000-0000-00000037b006', 'ci-is-a-spc', 'spc:1', 'https://screen.example.test/products/42',
   'CI Screenamine 10 mg: SmPC 4.4 changed', 'en', 'label_change', '2026-11-05', '2026-11-05 08:00+00', false,
   '{"sections":["4.4"]}'),
  ('00000000-0000-0000-0000-00000037b007', 'ci-is-a-feed', 'h7', 'https://screen.example.test/item-7',
   'CI otheramine only', 'en', 'dhpc', '2026-11-05', '2026-11-05 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000037b008', 'ci-is-f-fda', 'D-1',
   'https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-1%22', 'CI SCREENAMINE tablets recall', 'en',
   'recall', '2026-11-06', '2026-11-06 08:00+00', false, '{"event_id":"12345"}'),
  ('00000000-0000-0000-0000-00000037b009', 'ci-is-a-feed', 'h9', 'https://screen.example.test/item-9',
   'CI screenamine, Sunday 00:30 in Cairo', 'en', 'dhpc', null, '2026-11-07 22:30+00', false, null),
  ('00000000-0000-0000-0000-00000037b011', 'ci-is-b-html', 'i1', 'https://institute.example.test/letters/1',
   'CI screenamine letter from the institute', 'en', 'dhpc', '2026-11-06', '2026-11-06 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000037b012', 'ci-is-a-spc', 'spc:2', '',
   'CI Screenamine 20 mg: SmPC 4.8 changed', 'en', 'label_change', '2026-11-06', '2026-11-06 08:00+00', false,
   '{"sections":["4.8"]}'),
  ('00000000-0000-0000-0000-00000037b013', 'ci-is-b-html', 'i3', 'https://institute.example.test/letters/3',
   'The zparentoids: a class letter', 'en', 'dhpc', '2026-11-04', '2026-11-04 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000037b020', 'ci-is-lit', '1', 'https://pubmed.ncbi.nlm.nih.gov/1/',
   'CI screenamine and the QT interval', 'en', 'literature', '2026-11-02', '2026-11-03 08:00+00', false,
   '{"pmid":"1","pmcid":"PMC9","pubmed_url":"https://pubmed.ncbi.nlm.nih.gov/1/",'
   '"pmc_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC9/","journal":"CI Journal","found_in":["pmc","pubmed"],'
   '"queries":[{"query":"CI screenamine","kind":"name","db":["pmc","pubmed"]}],"class_only":false,"look_back":false}'),
  ('00000000-0000-0000-0000-00000037b021', 'ci-is-lit', 'PMC8', 'https://pmc.ncbi.nlm.nih.gov/articles/PMC8/',
   'A review of the screenoids', 'en', 'literature', '2026-11-05', '2026-11-05 08:00+00', false,
   '{"pmid":null,"pmcid":"PMC8","pubmed_url":null,"pmc_url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC8/",'
   '"journal":"CI Reviews","found_in":["pmc"],"queries":[{"query":"ci screenoids","kind":"class","db":["pmc"]},'
   '{"query":"ci otheramine","kind":"name","db":["pmc"]}],"class_only":true,"look_back":true}'),
  ('00000000-0000-0000-0000-00000037b022', 'ci-is-lit', '3', 'https://pubmed.ncbi.nlm.nih.gov/3/',
   'CI screenamine, a month before', 'en', 'literature', '2026-10-01', '2026-10-02 08:00+00', false,
   '{"pmid":"3","pubmed_url":"https://pubmed.ncbi.nlm.nih.gov/3/","found_in":["pubmed"],'
   '"queries":[{"query":"CI screenamine","kind":"name","db":["pubmed"]}]}');

insert into match (document_id, ingredient_id, class_id, term_id, class_term_id, field, matched_text) values
  ('00000000-0000-0000-0000-00000037b001', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'title', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b001', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'body', 'ci SCREENAMINE '),
  ('00000000-0000-0000-0000-00000037b002', null, '00000000-0000-0000-0000-00000037d001',
   null, '00000000-0000-0000-0000-00000037d102', 'title', 'CI-Screenoide'),
  ('00000000-0000-0000-0000-00000037b003', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'body', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b004', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'title', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b005', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'title', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b006', '00000000-0000-0000-0000-00000037a001', null,
   null, null, 'structured', 'CI Screenamine 10 mg'),
  ('00000000-0000-0000-0000-00000037b007', '00000000-0000-0000-0000-00000037a002', null,
   '00000000-0000-0000-0000-00000037c003', null, 'title', 'CI otheramine'),
  ('00000000-0000-0000-0000-00000037b008', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'structured', 'CI SCREENAMINE'),
  ('00000000-0000-0000-0000-00000037b009', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'title', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b011', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'title', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b012', '00000000-0000-0000-0000-00000037a001', null,
   null, null, 'structured', 'CI Screenamine 20 mg'),
  ('00000000-0000-0000-0000-00000037b013', null, '00000000-0000-0000-0000-00000037d002',
   null, '00000000-0000-0000-0000-00000037d201', 'title', 'zparentoids'),
  ('00000000-0000-0000-0000-00000037b020', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'structured', 'CI screenamine'),
  ('00000000-0000-0000-0000-00000037b021', null, '00000000-0000-0000-0000-00000037d001',
   null, '00000000-0000-0000-0000-00000037d101', 'structured', 'ci screenoids'),
  ('00000000-0000-0000-0000-00000037b022', '00000000-0000-0000-0000-00000037a001', null,
   '00000000-0000-0000-0000-00000037c001', null, 'structured', 'CI screenamine');

-- Notices: b001 is the anchor of its own; it is also a copy in the week-before notice and only suggested
-- for a third. b002's notice was opened by the check of the past (history).
insert into issue (id, doc_type, title, anchor_document_id, first_date, is_backfill, class_only) values
  ('00000000-0000-0000-0000-00000037e001', 'dhpc', 'CI screenamine: new warning',
   '00000000-0000-0000-0000-00000037b001', '2026-11-03', false, false),
  ('00000000-0000-0000-0000-00000037e002', 'safety_update', 'Die CI-Screenoide: Klassenwarnung',
   '00000000-0000-0000-0000-00000037b002', null, true, true),
  ('00000000-0000-0000-0000-00000037e004', 'dhpc', 'CI screenamine, the week before',
   '00000000-0000-0000-0000-00000037b004', '2026-10-30', false, false),
  ('00000000-0000-0000-0000-00000037e006', 'label_change', 'CI Screenamine 10 mg: SmPC 4.4 changed',
   '00000000-0000-0000-0000-00000037b006', '2026-11-05', false, false),
  ('00000000-0000-0000-0000-00000037e009', 'dhpc', 'Suggested only', null, null, false, false);
insert into issue_document (issue_id, document_id, link, method) values
  ('00000000-0000-0000-0000-00000037e004', '00000000-0000-0000-0000-00000037b001', 'copy', 'auto'),
  ('00000000-0000-0000-0000-00000037e009', '00000000-0000-0000-0000-00000037b001', 'copy', 'suggested'),
  ('00000000-0000-0000-0000-00000037e001', '00000000-0000-0000-0000-00000037b001', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000037e002', '00000000-0000-0000-0000-00000037b002', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000037e004', '00000000-0000-0000-0000-00000037b004', 'anchor', 'auto'),
  ('00000000-0000-0000-0000-00000037e006', '00000000-0000-0000-0000-00000037b006', 'anchor', 'auto');

-- ───────────── the shared link rule ─────────────
select pg_temp.is_assert(
  (select string_agg(coalesce(document_link(d, s, r), '-'), ' ' order by d.id)
     from document d join source s on s.id = d.source_id join regulator r on r.id = s.regulator_id
    where d.id in ('00000000-0000-0000-0000-00000037b001', '00000000-0000-0000-0000-00000037b002',
                   '00000000-0000-0000-0000-00000037b003', '00000000-0000-0000-0000-00000037b008',
                   '00000000-0000-0000-0000-00000037b012'))
  = 'https://screen.example.test/item-1 https://screen.example.test/safety - '
    || 'https://www.accessdata.fda.gov/scripts/ires/index.cfm?Event=12345 https://screen.example.test/products',
  'a link is the notice''s own page, the source''s page for a feed or an empty address, FDA''s Enforcement Report '
  || 'for an openFDA recall, and none for an e-mail');

-- ───────────── a decision on b001's notice, by an administrator ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into review_event (issue_id, from_status, to_status, comment, person_id)
  values ('00000000-0000-0000-0000-00000037e001', 'new', 'not_relevant', 'Another salt, not our product',
          my_person_id());
reset role;

-- ───────────── the screen, as a reader ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07')::text as is_week \gset
select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-08')::text as is_eight \gset
select string_agg(document_id::text || '|' || coalesce(pubmed_url, '-') || '|' || coalesce(pmc_url, '-') || '|'
                  || by_class || '|' || is_backfill || '|' || coalesce(journal, '-') || '|' || day, ' '
                  order by document_id)
         as is_papers
  from ingredient_papers('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07') \gset
select string_agg(source_id || ':' || coalesce(link, '-'), ' ' order by document_id) as is_new_items
  from new_items('2026-10-31 22:00+00', '2026-11-08 22:00+00')
 where document_id in ('00000000-0000-0000-0000-00000037b002', '00000000-0000-0000-0000-00000037b008') \gset
select pg_temp.is_refused($q$select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2026-11-07', '2026-11-01')$q$)
  as is_backwards \gset
select pg_temp.is_refused($q$select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2025-11-01', '2026-11-07')$q$)
  as is_too_long \gset
select pg_temp.is_refused($q$select ingredient_screen('00000000-0000-0000-0000-0000003700ff', '2026-11-01', '2026-11-07')$q$)
  as is_unknown \gset
select pg_temp.is_refused($q$select ingredient_screen_check('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07')$q$)
  as is_check_direct \gset
reset role;

-- the parent class switched on: its words count, and are due for the check of the past again
update class_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00' where id = '00000000-0000-0000-0000-00000037d201';
update ingredient_class set enabled = true
 where ingredient_id = '00000000-0000-0000-0000-00000037a001' and class_id = '00000000-0000-0000-0000-00000037d002';
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07')::text as is_week_on \gset
reset role;

create temp table is_res (name text primary key, j jsonb);
insert into is_res values ('week', :'is_week'::jsonb), ('eight', :'is_eight'::jsonb);
create function pg_temp.is_reg(which text, reg text) returns jsonb language sql as $$
  select r from is_res, jsonb_array_elements(j -> 'regulators') r where name = which and r ->> 'id' = reg
$$;
create function pg_temp.is_docs(arr jsonb) returns text language sql as $$
  select coalesce(string_agg(right(m ->> 'document_id', 4), ',' order by o), '')
    from jsonb_array_elements(arr) with ordinality as x(m, o)
$$;

-- who is listed, in which order
select pg_temp.is_assert(
  (select string_agg(r ->> 'id', ',' order by o)
     from is_res, jsonb_array_elements(j -> 'regulators') with ordinality as x(r, o)
    where name = 'week' and r ->> 'id' like 'CI-IS-%') = 'CI-IS-D,CI-IS-C,CI-IS-A,CI-IS-E,CI-IS-F,CI-IS-B',
  'her authorities first, by country, then the others; a library with papers only is not an authority');
select pg_temp.is_assert(
  (pg_temp.is_reg('week', 'CI-IS-A') ->> 'hers')::boolean and not (pg_temp.is_reg('week', 'CI-IS-B') ->> 'hers')::boolean
    and pg_temp.is_reg('week', 'CI-IS-A') ->> 'country_name' = 'CI Screenland'
    and jsonb_array_length(pg_temp.is_reg('week', 'CI-IS-A') -> 'sources') = 3
    and pg_temp.is_reg('week', 'CI-IS-A') -> 'pages' -> 0 ->> 'label' = 'CI Screenland safety page'
    and pg_temp.is_reg('week', 'CI-IS-A') -> 'pages' -> 0 -> 'read_by' = '["ci-is-a-feed"]'::jsonb,
  'each authority says whether it is hers, with her pages and its sources');

-- reads
select pg_temp.is_assert(
  (select string_agg(r ->> 'id' || ':' || (r ->> 'runs') || '/' || (r ->> 'ok') || '/' || (r ->> 'failed') || '/'
                     || (r ->> 'unread_page'), ' ' order by r ->> 'id')
     from is_res, jsonb_array_elements(j -> 'regulators') r
    where name = 'week' and r ->> 'id' like 'CI-IS-%')
  = 'CI-IS-A:1/1/0/false CI-IS-B:0/0/0/false CI-IS-C:3/3/0/false CI-IS-D:2/1/1/false CI-IS-E:0/0/0/true '
    || 'CI-IS-F:1/1/0/false',
  'reads are counted in Cairo days from the safety and recall sources; a note is not a failure; a page read '
  || 'only by a switched-off source is unread; a database page does not count');

-- mentions
select pg_temp.is_assert(pg_temp.is_docs(pg_temp.is_reg('week', 'CI-IS-A') -> 'mentions') = 'b002,b003,b001,b005',
  'the mentions of the week, newest first: another ingredient, the week before, a label and Sunday 00:30 are '
  || 'left out');
select pg_temp.is_assert(pg_temp.is_docs(pg_temp.is_reg('eight', 'CI-IS-A') -> 'mentions') = 'b009,b002,b003,b001,b005',
  'a notice first seen at 00:30 on Sunday in Cairo belongs to Sunday');
select pg_temp.is_assert(pg_temp.is_docs(pg_temp.is_reg('week', 'CI-IS-B') -> 'mentions') = 'b011,b013'
    and pg_temp.is_docs(pg_temp.is_reg('week', 'CI-IS-C') -> 'mentions') = ''
    and pg_temp.is_docs(pg_temp.is_reg('week', 'CI-IS-F') -> 'mentions') = 'b008',
  'each authority has its own mentions');

create function pg_temp.is_mention(reg text, doc text) returns jsonb language sql as $$
  select m from jsonb_array_elements(pg_temp.is_reg('week', reg) -> 'mentions') m
   where m ->> 'document_id' = '00000000-0000-0000-0000-00000037' || doc
$$;
select pg_temp.is_assert(
  pg_temp.is_mention('CI-IS-A', 'b001') ->> 'title' = 'CI screenamine: new warning'
    and pg_temp.is_mention('CI-IS-A', 'b001') ->> 'link' = 'https://screen.example.test/item-1'
    and pg_temp.is_mention('CI-IS-A', 'b001') ->> 'date' = '2026-11-03'
    and pg_temp.is_mention('CI-IS-A', 'b001') ->> 'doc_type' = 'dhpc'
    and pg_temp.is_mention('CI-IS-A', 'b001') ->> 'source_id' = 'ci-is-a-feed'
    and pg_temp.is_mention('CI-IS-A', 'b001') -> 'terms' = '[{"text":"CI screenamine","lang":"en"}]'::jsonb
    and not (pg_temp.is_mention('CI-IS-A', 'b001') ->> 'by_class')::boolean
    and not (pg_temp.is_mention('CI-IS-A', 'b001') ->> 'is_backfill')::boolean,
  'a mention carries its title, link, date, type, source and the words that matched (once each, any case)');
select pg_temp.is_assert(
  pg_temp.is_mention('CI-IS-A', 'b001') ->> 'issue_id' = '00000000-0000-0000-0000-00000037e001'
    and pg_temp.is_mention('CI-IS-A', 'b001') ->> 'issue_status' = 'not_relevant'
    and pg_temp.is_mention('CI-IS-A', 'b001') -> 'decision' ->> 'to_status' = 'not_relevant'
    and pg_temp.is_mention('CI-IS-A', 'b001') -> 'decision' ->> 'person' = 'CI Admin'
    and pg_temp.is_mention('CI-IS-A', 'b001') -> 'decision' ->> 'comment' = 'Another salt, not our product'
    and (pg_temp.is_mention('CI-IS-A', 'b001') -> 'decision' ->> 'at') is not null,
  'a mention carries its own notice (not a copy elsewhere, not a suggestion), its status and the latest decision');
select pg_temp.is_assert(
  (pg_temp.is_mention('CI-IS-A', 'b002') ->> 'by_class')::boolean
    and (pg_temp.is_mention('CI-IS-A', 'b002') ->> 'is_backfill')::boolean
    and pg_temp.is_mention('CI-IS-A', 'b002') -> 'terms' = '[{"text":"CI-Screenoide","lang":"de"}]'::jsonb
    and pg_temp.is_mention('CI-IS-A', 'b002') ->> 'link' = 'https://screen.example.test/safety'
    and pg_temp.is_mention('CI-IS-A', 'b002') ->> 'date' = '2026-11-07'
    and pg_temp.is_mention('CI-IS-A', 'b002') ->> 'issue_status' = 'new'
    and pg_temp.is_mention('CI-IS-A', 'b002') -> 'decision' = 'null'::jsonb,
  'a class word alone is by class; a notice opened by the check of the past is history; no decision yet');
select pg_temp.is_assert(
  pg_temp.is_mention('CI-IS-A', 'b001') ->> 'relation' = 'name'
    and pg_temp.is_mention('CI-IS-A', 'b001') -> 'class_name' = 'null'::jsonb
    and pg_temp.is_mention('CI-IS-A', 'b002') ->> 'relation' = 'group'
    and pg_temp.is_mention('CI-IS-A', 'b002') ->> 'class_name' = 'CI screenoids'
    and pg_temp.is_mention('CI-IS-B', 'b013') ->> 'relation' = 'parent'
    and pg_temp.is_mention('CI-IS-B', 'b013') ->> 'class_name' = 'CI zparentoids'
    and (pg_temp.is_mention('CI-IS-B', 'b013') ->> 'by_class')::boolean,
  'each mention says how it was found: by name, by the group, or by the parent class (named)');
select pg_temp.is_assert(
  ingredient_match_relation('00000000-0000-0000-0000-00000037a001', '00000000-0000-0000-0000-00000037b001') = 'name'
    and ingredient_match_relation('00000000-0000-0000-0000-00000037a001', '00000000-0000-0000-0000-00000037b002') = 'group'
    and ingredient_match_relation('00000000-0000-0000-0000-00000037a001', '00000000-0000-0000-0000-00000037b013') = 'parent'
    and ingredient_match_relation('00000000-0000-0000-0000-00000037a002', '00000000-0000-0000-0000-00000037b001') is null,
  'ingredient_match_relation: the name first, then the nearest class; nothing for another ingredient');
select pg_temp.is_assert(
  pg_temp.is_mention('CI-IS-A', 'b003') -> 'link' = 'null'::jsonb
    and pg_temp.is_mention('CI-IS-A', 'b003') ->> 'email_id' = '00000000-0000-0000-0000-00000037e0e1'
    and pg_temp.is_mention('CI-IS-A', 'b003') ->> 'email_r2_key' = 'inbound/2026-11-04/ci-is.eml'
    and pg_temp.is_mention('CI-IS-A', 'b003') -> 'issue_id' = 'null'::jsonb
    and (pg_temp.is_mention('CI-IS-A', 'b005') ->> 'is_backfill')::boolean
    and pg_temp.is_mention('CI-IS-F', 'b008') ->> 'link'
        = 'https://www.accessdata.fda.gov/scripts/ires/index.cfm?Event=12345',
  'an e-mail opens from the mailbox; a backfilled notice is history; an openFDA recall links to the report');
select pg_temp.is_assert(:'is_new_items'
    = 'ci-is-a-feed:https://screen.example.test/safety '
      || 'ci-is-f-fda:https://www.accessdata.fda.gov/scripts/ires/index.cfm?Event=12345',
  'new_items() on Sources gives the same links');

-- label changes
select pg_temp.is_assert(
  pg_temp.is_docs((select j -> 'label_changes' from is_res where name = 'week')) = 'b012,b006'
    and (select j -> 'label_changes' -> 1 ->> 'link' from is_res where name = 'week') = 'https://screen.example.test/products/42'
    and (select j -> 'label_changes' -> 0 ->> 'link' from is_res where name = 'week') = 'https://screen.example.test/products'
    and (select j -> 'label_changes' -> 1 -> 'sections' from is_res where name = 'week') = '["4.4"]'::jsonb
    and (select j -> 'label_changes' -> 1 ->> 'issue_id' from is_res where name = 'week')
        = '00000000-0000-0000-0000-00000037e006'
    and (select j -> 'label_changes' -> 1 ->> 'country_name' from is_res where name = 'week') = 'CI Screenland',
  'label changes come apart, newest first, linked to the product page, with the sections and their notice');

-- the ingredient
select pg_temp.is_assert(
  (select j -> 'ingredient' ->> 'inn_en' = 'CI screenamine'
          and j -> 'ingredient' ->> 'atc_code' = 'Z99ZZ01'
          and j -> 'ingredient' -> 'classes' -> 0 ->> 'name_en' = 'CI screenoids'
          and (j -> 'ingredient' ->> 'names')::int = 2
          and (j -> 'ingredient' ->> 'name_languages')::int = 2
          and (j -> 'ingredient' ->> 'class_words')::int = 2
          and (j -> 'ingredient' ->> 'class_languages')::int = 2
          and j ->> 'from' = '2026-11-01' and j ->> 'to' = '2026-11-07'
     from is_res where name = 'week'),
  'the head of the screen: the name, the ATC code, the classes and what is searched');
select pg_temp.is_assert(
  (select j -> 'ingredient' -> 'classes' -> 0 ->> 'relation' = 'group'
          and (j -> 'ingredient' -> 'classes' -> 0 ->> 'enabled')::boolean
          and j -> 'ingredient' -> 'classes' -> 1 ->> 'name_en' = 'CI zparentoids'
          and j -> 'ingredient' -> 'classes' -> 1 ->> 'relation' = 'parent'
          and not (j -> 'ingredient' -> 'classes' -> 1 ->> 'enabled')::boolean
     from is_res where name = 'week'),
  'each class says what it is to the ingredient and whether its words are searched');
select pg_temp.is_assert(
  (:'is_week_on'::jsonb -> 'ingredient' ->> 'class_words')::int = 3
    and (:'is_week_on'::jsonb -> 'ingredient' -> 'classes' -> 1 ->> 'enabled')::boolean
    and (select rematched_at < changed_at from class_term where id = '00000000-0000-0000-0000-00000037d201'),
  'the parent class switched on: its words are counted and due for the check of the past again');

-- literature
select pg_temp.is_assert(
  (select (j -> 'literature' ->> 'papers')::int = 2
          and (j -> 'literature' ->> 'by_name')::int = 1
          and (j -> 'literature' ->> 'by_class')::int = 1
          and (j -> 'literature' ->> 'pubmed')::int = 1
          and (j -> 'literature' ->> 'pmc')::int = 2
          and j -> 'literature' -> 'by_query' = '[{"query":"ci screenamine","kind":"name","pubmed":1,"pmc":1,"europepmc":0},'
                                                 '{"query":"ci screenoids","kind":"class","pubmed":0,"pmc":1,'
                                                 '"europepmc":0}]'::jsonb
          and pg_temp.is_docs(j -> 'literature' -> 'first') = 'b020,b021'
     from is_res where name = 'week'),
  'papers: in all, by database and by search of this ingredient, the name''s papers first');
select pg_temp.is_assert(:'is_papers' =
    '00000000-0000-0000-0000-00000037b020|https://pubmed.ncbi.nlm.nih.gov/1/|https://pmc.ncbi.nlm.nih.gov/articles/PMC9/'
    || '|false|false|CI Journal|2026-11-02 '
    || '00000000-0000-0000-0000-00000037b021|-|https://pmc.ncbi.nlm.nih.gov/articles/PMC8/|true|true|CI Reviews|2026-11-05',
  'ingredient_papers gives both links, the journal, by class and history (a first look-back)');

-- refusals
select pg_temp.is_assert(:'is_backwards' like '22023%' and :'is_too_long' like '22023%' and :'is_unknown' like 'P0002%',
  'days that end before they start, more than 366 days, or an unknown ingredient are refused');
select pg_temp.is_assert(:'is_check_direct' like '42501%', 'the check alone is not callable from the app');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.is_refused($q$select ingredient_screen('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07')$q$)
  as is_stranger \gset
select pg_temp.is_refused($q$select * from ingredient_papers('00000000-0000-0000-0000-00000037a001', '2026-11-01', '2026-11-07')$q$)
  as is_stranger_papers \gset
reset role;
select pg_temp.is_assert(:'is_stranger' like '42501%' and :'is_stranger_papers' like '42501%',
  'someone signed in but not on the team is refused');
select pg_temp.is_assert(
  not has_function_privilege('anon', 'public.ingredient_screen(uuid, date, date)', 'execute')
    and not has_function_privilege('anon', 'public.ingredient_papers(uuid, date, date)', 'execute')
    and not has_function_privilege('anon', 'public.document_link(document, source, regulator)', 'execute')
    and has_function_privilege('authenticated', 'public.ingredient_screen(uuid, date, date)', 'execute'),
  'signed-out visitors can call none of it');

rollback;
