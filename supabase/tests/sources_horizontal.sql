-- PHAROS CI — the horizontal pass on Sources (0032, 0033, 0038). Runs on the database ci.yml prepared:
-- CI Admin (…a1), CI Reader (…b2) and the source ci-test exist.

create function pg_temp.sh_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- ───────────── her list ─────────────
select pg_temp.sh_assert((select count(distinct regulator_id) from regulator_page) = 25,
  'her 25 reference authorities are listed');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'BASG' and kind = 'dhpc' and read_by = '{basg-dhpc}'),
  'BASG''s DHPC page is read by basg-dhpc');
select pg_temp.sh_assert(not exists (select 1 from regulator_page where url !~ '^https://'),
  'every page of hers is an https address');

-- ───────────── her pages read since 0038 ─────────────
select pg_temp.sh_assert((select count(*) from regulator_page) = 65, 'her 65 pages, none added or lost');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'EMA' and kind = 'safety' and read_by = '{ema-news}'),
  'EMA''s home page news is read by ema-news');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'SWISSMEDIC' and kind = 'safety' and read_by = '{swissmedic-updates}'),
  'Swissmedic''s updates are read by swissmedic-updates');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'MEDSAFE' and label = 'Prescriber Update'
                                    and read_by = '{medsafe-prescriber-update}'),
  'Prescriber Update is read by medsafe-prescriber-update');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'PMDA' and label = 'Safety information announced by MHLW'
                                    and read_by = '{pmda-mhlw}' and note like 'Read from the Japanese page%'),
  'the MHLW announcements are read by pmda-mhlw, from the Japanese page');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'INFARMED' and kind = 'dhpc' and read_by = '{infarmed-circulares}'),
  'Infarmed''s circulars are read by infarmed-circulares');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'MFDS' and kind = 'safety' and read_by = '{mfds-letters}'),
  'the health.kr safety letters are read by mfds-letters');
select pg_temp.sh_assert(exists (select 1 from regulator_page
                                  where regulator_id = 'HPRA' and kind = 'safety'
                                    and url = 'https://www.hpra.ie/safety-information/safety-notices'
                                    and read_by = '{hpra-notices}'
                                    and note like '%https://www.hpra.ie/homepage/about-us/publications-forms/newsletters%'),
  'HPRA''s newsletters: the page that replaced her dead address, read by hpra-notices, her address in the note');
select pg_temp.sh_assert(not exists (select 1 from regulator_page
                                      where kind <> 'database' and read_by = '{}'
                                        and coalesce(note, '') not like 'Not read:%'),
  'every safety and DHPC page of hers is read, or its note says why not');
select pg_temp.sh_assert((select string_agg(regulator_id, ',' order by regulator_id) from regulator_page
                           where kind <> 'database' and read_by = '{}') = 'FDA,HC',
  'only FDA''s press announcements and Health Canada''s InfoWatch are not read');

-- ───────────── two authorities of one country, one of another ─────────────
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-SH-A', 'XA', 'CI Horizon', 'CI Horizon Agency', '{en}', 'https://horizon.example.test/'),
  ('CI-SH-B', 'XA', 'CI Horizon', 'CI Horizon Institute', '{en}', null),
  ('CI-SH-C', 'XC', 'CI Elsewhere', 'CI Elsewhere Agency', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url) values
  ('ci-sh-feed', 'CI-SH-A', 'safety', 'rss', 'https://horizon.example.test/feed.xml', 'feed', '{en}',
   'https://horizon.example.test/safety'),
  ('ci-sh-fda', 'CI-SH-A', 'recall', 'api', 'https://api.fda.gov/drug/enforcement.json', 'openfda_enforcement',
   '{en}', 'https://www.accessdata.fda.gov/scripts/ires/index.cfm'),
  ('ci-sh-mail', 'CI-SH-B', 'safety', 'email', 'https://horizon.example.test/news', 'email_inbox', '{en}',
   'https://horizon.example.test/news'),
  ('ci-sh-spc', 'CI-SH-A', 'spc', 'api', 'https://horizon.example.test/spc', 'ci', '{en}', null),
  ('ci-sh-lit', 'CI-SH-C', 'literature', 'api', 'https://horizon.example.test/lit', 'ci', '{en}', null);
insert into ingredient (id, inn_en) values ('00000000-0000-0000-0000-00000007a001', 'CI horizonamine');

-- The week: Sunday 1 Nov 2026 22:00 UTC (Monday 00:00 Cairo) to a week later.
insert into document (id, source_id, external_id, url, title_orig, lang, first_seen_at, is_backfill, structured) values
  ('00000000-0000-0000-0000-00000007b001', 'ci-sh-feed', 'h1', 'https://horizon.example.test/item-1',
   'CI horizonamine: new warning', 'en', '2026-11-02 08:00+00', false, null),
  ('00000000-0000-0000-0000-00000007b002', 'ci-sh-feed', 'h2', 'https://horizon.example.test/feed.xml?id=2',
   'An item whose only link is the feed', 'en', '2026-11-02 09:00+00', false, null),
  ('00000000-0000-0000-0000-00000007b003', 'ci-sh-fda', 'D-0062-2027',
   'https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-0062-2027%22',
   'A recall stored before 0032', 'en', '2026-11-03 08:00+00', false, '{"event_id":"99849"}'),
  ('00000000-0000-0000-0000-00000007b004', 'ci-sh-fda', 'D-0063-2027',
   'https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-0063-2027%22',
   'A recall without an event id', 'en', '2026-11-03 09:00+00', false, '{}'),
  ('00000000-0000-0000-0000-00000007b005', 'ci-sh-mail', 'email:00000000-0000-0000-0000-00000007e001',
   'email:00000000-0000-0000-0000-00000007e001', 'A bulletin with no web page', 'en', '2026-11-04 08:00+00', false,
   '{"inbound_email_id":"00000000-0000-0000-0000-00000007e001","raw_r2_key":"inbound/2026-11-04/ci.eml"}'),
  ('00000000-0000-0000-0000-00000007b006', 'ci-sh-feed', 'h6', 'https://horizon.example.test/item-6',
   'History from a backfill', 'en', '2026-11-02 10:00+00', true, null),
  ('00000000-0000-0000-0000-00000007b007', 'ci-sh-spc', 's7', 'https://horizon.example.test/spc/7',
   'A label from the label watch', 'en', '2026-11-02 11:00+00', false, null),
  ('00000000-0000-0000-0000-00000007b008', 'ci-sh-lit', 'l8', 'https://horizon.example.test/lit/8',
   'A paper', 'en', '2026-11-02 12:00+00', false, null),
  ('00000000-0000-0000-0000-00000007b009', 'ci-sh-feed', 'h9', 'https://horizon.example.test/item-9',
   'Seen the week before', 'en', '2026-10-30 08:00+00', false, null);
insert into match (document_id, ingredient_id, field, matched_text) values
  ('00000000-0000-0000-0000-00000007b001', '00000000-0000-0000-0000-00000007a001', 'title', 'CI horizonamine');

-- ───────────── new_items, as a reader ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select count(*) as sh_n,
       string_agg(source_id || ':' || coalesce(link, '-'), ' ' order by first_seen_at) as sh_links,
       count(*) filter (where matched) as sh_matched,
       string_agg(document_id::text, ' ' order by first_seen_at) filter (where matched) as sh_matched_id
  from new_items('2026-11-01 22:00+00', '2026-11-08 22:00+00') where source_id like 'ci-sh-%' \gset
select email_id::text as sh_email_id, email_r2_key as sh_email_key, coalesce(link, 'null') as sh_email_link
  from new_items('2026-11-01 22:00+00', '2026-11-08 22:00+00')
 where document_id = '00000000-0000-0000-0000-00000007b005' \gset
select count(*) as sh_open_end from new_items('2026-11-01 22:00+00', null) where source_id like 'ci-sh-%' \gset
select count(*) as sh_pages_reader from regulator_page \gset
reset role;

select pg_temp.sh_assert(:sh_n = 5, 'history, the label watch, literature and last week are left out');
select pg_temp.sh_assert(:'sh_links' =
    'ci-sh-feed:https://horizon.example.test/item-1 '
    || 'ci-sh-feed:https://horizon.example.test/safety '
    || 'ci-sh-fda:https://www.accessdata.fda.gov/scripts/ires/index.cfm?Event=99849 '
    || 'ci-sh-fda:https://www.accessdata.fda.gov/scripts/ires/index.cfm '
    || 'ci-sh-mail:-',
  'each item links to a page: its own, the source''s page for a feed link, FDA''s Enforcement Report for a recall');
select pg_temp.sh_assert(:sh_matched = 1 and :'sh_matched_id' = '00000000-0000-0000-0000-00000007b001',
  'an item that matched a watched ingredient says so');
select pg_temp.sh_assert(:'sh_email_link' = 'null' and :'sh_email_id' = '00000000-0000-0000-0000-00000007e001'
    and :'sh_email_key' = 'inbound/2026-11-04/ci.eml',
  'an e-mail with no web page opens from the mailbox and the archive');
select pg_temp.sh_assert(:sh_open_end = 5, 'no end means up to now');
select pg_temp.sh_assert(:sh_pages_reader = (select count(*) from regulator_page) and :sh_pages_reader >= 65,
  'a reader reads every one of her pages');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as sh_stranger from new_items('2026-11-01 22:00+00', '2026-11-08 22:00+00') \gset
select count(*) as sh_stranger_pages from regulator_page \gset
do $$ declare refused boolean := false; begin
  begin perform mark_country_looked('CI-SH-A'); exception when insufficient_privilege then refused := true; end;
  if not refused then raise exception 'FAIL: someone not on the team marked a country as looked at'; end if;
end $$;
reset role;
select pg_temp.sh_assert(:sh_stranger = 0 and :sh_stranger_pages = 0, 'someone not on the team sees nothing');
select pg_temp.sh_assert(not has_function_privilege('anon', 'public.new_items(timestamptz, timestamptz)', 'execute')
    and not has_function_privilege('anon', 'public.mark_country_looked(text)', 'execute')
    and not has_table_privilege('anon', 'public.regulator_page', 'select'),
  'signed-out visitors can call and read none of it');

-- ───────────── her pages: admins write, readers do not ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into regulator_page (regulator_id, kind, sort, label, url, read_by)
  values ('CI-SH-A', 'safety', 1, 'CI safety page', 'https://horizon.example.test/safety', '{ci-sh-feed}');
do $$ declare refused boolean := false; begin
  begin
    insert into regulator_page (regulator_id, kind, label, url) values ('CI-NONE', 'safety', 'x', 'https://x.example.test/');
  exception when foreign_key_violation then refused := true; end;
  if not refused then raise exception 'FAIL: a page was added for an authority PHAROS does not know'; end if;
end $$;
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
do $$ declare refused boolean := false; begin
  begin
    insert into regulator_page (regulator_id, kind, label, url) values ('CI-SH-A', 'dhpc', 'x', 'https://horizon.example.test/x');
  exception when insufficient_privilege then refused := true; end;
  if not refused then raise exception 'FAIL: a reader added a page'; end if;
end $$;
update regulator_page set label = 'changed by a reader' where regulator_id = 'CI-SH-A';
reset role;
select pg_temp.sh_assert((select string_agg(label, ',') from regulator_page where regulator_id = 'CI-SH-A') = 'CI safety page',
  'an admin adds a page; a reader neither adds nor changes one');
select pg_temp.sh_assert(exists (select 1 from audit_log where table_name = 'regulator_page'
                                    and new_row ->> 'label' = 'CI safety page'),
  'a change to her pages is in the audit log');

-- ───────────── Mark as looked at ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select mark_country_looked('CI-SH-B')::text as sh_at \gset
select string_agg(regulator_id, ',' order by regulator_id) as sh_mine from v_my_country_look
 where regulator_id like 'CI-SH-%' \gset
do $$ declare refused boolean := false; begin
  begin
    insert into country_look (person_id, regulator_id) values (my_person_id(), 'CI-SH-C');
  exception when insufficient_privilege then refused := true; end;
  if not refused then raise exception 'FAIL: a look was written without mark_country_looked'; end if;
  refused := false;
  begin perform mark_country_looked('CI-NONE'); exception when invalid_parameter_value then refused := true; end;
  if not refused then raise exception 'FAIL: an unknown authority was marked'; end if;
end $$;
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select count(*) as sh_admin_looks from v_my_country_look where regulator_id like 'CI-SH-%' \gset
select count(*) as sh_admin_reads_all from country_look where regulator_id like 'CI-SH-%' \gset
reset role;
select pg_temp.sh_assert(:'sh_mine' = 'CI-SH-A,CI-SH-B', 'one look stamps every authority of the country, and only that country');
select pg_temp.sh_assert((select bool_and(person_id = (select id from person where email = 'reader@example.test')
                                          and looked_at = :'sh_at'::timestamptz)
                            from country_look where regulator_id like 'CI-SH-%'),
  'a look is the signed-in person''s, at the database''s time');
select pg_temp.sh_assert(:sh_admin_looks = 0 and :sh_admin_reads_all = 2,
  'each person has their own last look; the team reads every look');

-- ───────────── the daily message: the new values and her subscription ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
insert into subscription (person_id, kind) values (my_person_id(), 'new_items_digest');
reset role;
select pg_temp.sh_assert(exists (select 1 from subscription s join person p on p.id = s.person_id
                                  where p.email = 'reader@example.test' and s.kind = 'new_items_digest'),
  'anyone on the team can switch the daily new-items message on for themselves');
insert into notification (person_id, kind, dry_run, summary)
  select id, 'new_items_digest', true, 'CI' from person where email = 'reader@example.test';

insert into person (full_name, email, role) values ('CI Sama', 'Sama.Mosaad@SatoPharma.com', 'admin');
\ir ../migrations/0033_sama_new_items_digest.sql
\ir ../migrations/0033_sama_new_items_digest.sql
select pg_temp.sh_assert((select count(*) from subscription s join person p on p.id = s.person_id
                           where p.email = 'Sama.Mosaad@SatoPharma.com' and s.kind = 'new_items_digest') = 1,
  'her subscription is added once, whatever the case of her address');
select pg_temp.sh_assert((select count(*) from subscription where kind = 'new_items_digest') = 2,
  'nobody else is subscribed by 0033');

-- ───────────── clean up ─────────────
delete from notification where kind = 'new_items_digest' and summary = 'CI';
delete from subscription where kind = 'new_items_digest'
  and person_id in (select id from person where email in ('reader@example.test', 'Sama.Mosaad@SatoPharma.com'));
delete from person where email = 'Sama.Mosaad@SatoPharma.com';
delete from document where source_id like 'ci-sh-%';
delete from source where id like 'ci-sh-%';
delete from regulator where id like 'CI-SH-%';
delete from ingredient where id = '00000000-0000-0000-0000-00000007a001';
