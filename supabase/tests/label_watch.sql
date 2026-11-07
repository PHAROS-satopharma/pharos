-- PHAROS CI — the label watch per database page (0091): label_watch(), label_watch_sources(), spc_listing and
-- spc_product.last_error. Runs on the database ci.yml prepared: CI Reader (…b2) exists. Everything here happens
-- in one transaction that is rolled back at the end.

begin;

create function pg_temp.lw_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.lw_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- ───────────── one ingredient, one regulator with two database pages: one read, one blocked ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000091a001', 'CI watchamine', 'Z91ZZ01'),
  ('00000000-0000-0000-0000-00000091a002', 'CI otherwatchamine', 'Z91ZZ02');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-LW-A', 'XW', 'CI Watchland', 'CI Watchland Agency', '{en}', 'https://watch.example.test/');
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-lw-spc', 'CI-LW-A', 'spc', 'api', 'https://watch.example.test/spc.json', 'ci', '{en}',
   'https://watch.example.test/products', true);
insert into regulator_page (regulator_id, kind, sort, label, url, read_by, partial, note) values
  ('CI-LW-A', 'database', 1, 'CI product database', 'https://watch.example.test/products', '{ci-lw-spc}', false,
   'Label watch, for our ingredients only.'),
  ('CI-LW-A', 'database', 2, 'CI old register', 'https://watch.example.test/register', '{}', false,
   'Not read: the register opens only after a sign-in.');

-- LW-1 read twice (labels dated 1 Jun and 1 Oct), one change; LW-2 never read, its last read failed;
-- LW-3 new, not read yet; LW-4 withdrawn (inactive); LW-5 another ingredient's.
insert into spc_product (id, ingredient_id, source_id, country_code, national_id, product_name, active,
                         last_error, last_error_at, checked_at) values
  ('00000000-0000-0000-0000-00000091d001', '00000000-0000-0000-0000-00000091a001', 'ci-lw-spc', 'XW', 'LW-1',
   'CI Watchamine 10 mg', true, null, null, '2026-11-02 08:00+00'),
  ('00000000-0000-0000-0000-00000091d002', '00000000-0000-0000-0000-00000091a001', 'ci-lw-spc', 'XW', 'LW-2',
   'CI Watchamine 20 mg', true, 'FetchError: HTTP 500 for https://watch.example.test/spc/LW-2.pdf',
   '2026-11-02 08:05+00', null),
  ('00000000-0000-0000-0000-00000091d003', '00000000-0000-0000-0000-00000091a001', 'ci-lw-spc', 'XW', 'LW-3',
   'CI Watchamine 40 mg', true, null, null, null),
  ('00000000-0000-0000-0000-00000091d004', '00000000-0000-0000-0000-00000091a001', 'ci-lw-spc', 'XW', 'LW-4',
   'CI Watchamine 5 mg', false, 'old error', '2026-10-01 08:00+00', null),
  ('00000000-0000-0000-0000-00000091d005', '00000000-0000-0000-0000-00000091a002', 'ci-lw-spc', 'XW', 'LW-5',
   'CI Otherwatchamine 1 mg', true, null, null, '2026-11-02 08:00+00');
insert into spc_snapshot (id, spc_product_id, fetched_at, doc_date, sha256, section_hashes) values
  ('00000000-0000-0000-0000-00000091f001', '00000000-0000-0000-0000-00000091d001', '2026-06-02 08:00+00', '2026-06-01', 'w1', '{}'),
  ('00000000-0000-0000-0000-00000091f002', '00000000-0000-0000-0000-00000091d001', '2026-11-02 08:00+00', '2026-10-01', 'w2', '{}'),
  ('00000000-0000-0000-0000-00000091f003', '00000000-0000-0000-0000-00000091d005', '2026-11-02 08:00+00', '2026-11-01', 'x1', '{}');
insert into spc_change (id, spc_product_id, from_snapshot, to_snapshot, sections, diff, created_at) values
  ('00000000-0000-0000-0000-00000091c001', '00000000-0000-0000-0000-00000091d001',
   '00000000-0000-0000-0000-00000091f001', '00000000-0000-0000-0000-00000091f002', '{4.4}', '[]',
   '2026-11-02 08:00+00');
insert into spc_listing (source_id, ingredient_id, listed_at, products, complete, gaps) values
  ('ci-lw-spc', '00000000-0000-0000-0000-00000091a001', '2026-11-02 07:59+00', 3, false, 'page 2: HTTP 503'),
  ('ci-lw-spc', '00000000-0000-0000-0000-00000091a002', '2026-11-02 07:58+00', 1, true, null);
insert into run (id, trigger, started_at) values ('00000000-0000-0000-0000-00000091e001', 'cron', '2026-11-02 07:50+00');
insert into source_run (run_id, source_id, started_at, finished_at, items_seen, error) values
  ('00000000-0000-0000-0000-00000091e001', 'ci-lw-spc', '2026-11-02 07:50+00', '2026-11-02 08:10+00', 4,
   '2 error(s); first: discover CI watchamine: partial list: page 2: HTTP 503');

-- ───────────── a team member reads it ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
create temp table lw on commit drop as select label_watch('00000000-0000-0000-0000-00000091a001') as j;
create temp table lws on commit drop as select label_watch_sources() as j;
reset role;

create temp table lw_page on commit drop as
  select x as page from lw, jsonb_array_elements(lw.j) x where x ->> 'regulator_id' = 'CI-LW-A';
create temp table lw_src on commit drop as
  select s as src from lw_page, jsonb_array_elements(page -> 'sources') s where page ->> 'label' = 'CI product database';

select pg_temp.lw_assert((select count(*) = 2 from lw_page), 'both of the regulator''s database pages are listed');
select pg_temp.lw_assert((select page -> 'sources' = '[]'::jsonb
                                 and page ->> 'note' = 'Not read: the register opens only after a sign-in.'
                            from lw_page where page ->> 'label' = 'CI old register'),
  'a page no source reads has no sources and keeps its reason');
select pg_temp.lw_assert((select page ->> 'country_name' = 'CI Watchland' and page ->> 'regulator' = 'CI Watchland Agency'
                            from lw_page where page ->> 'label' = 'CI product database'),
  'a page names its country and regulator');
select pg_temp.lw_assert((select (src ->> 'products')::int = 3 from lw_src),
  'products: the ingredient''s active ones only (the withdrawn one and the other ingredient''s left out)');
select pg_temp.lw_assert((select (src ->> 'labels_read')::int = 1 and (src ->> 'unread')::int = 1
                                 and (src ->> 'waiting')::int = 1 from lw_src),
  'one label read, one unread with an error, one not read yet');
select pg_temp.lw_assert((select src -> 'errors' -> 0 ->> 'product' = 'CI Watchamine 20 mg'
                                 and src -> 'errors' -> 0 ->> 'error' like 'FetchError: HTTP 500%'
                                 and jsonb_array_length(src -> 'errors') = 1 from lw_src),
  'the unread label is named with its error; a withdrawn product''s old error is not');
select pg_temp.lw_assert((select src ->> 'latest_label_date' = '2026-10-01'
                                 and (src ->> 'latest_change_at')::timestamptz = '2026-11-02 08:00+00' from lw_src),
  'the newest label date and the newest change detected, of this ingredient''s products');
select pg_temp.lw_assert((select (src ->> 'lists_broken')::int = 1 and src ->> 'gaps' = 'page 2: HTTP 503' from lw_src),
  'a list that broke off says so, and where');
select pg_temp.lw_assert((select (src -> 'last_run' ->> 'failed')::boolean = false
                                 and src -> 'last_run' ->> 'error' like '2 error(s)%' from lw_src),
  'the source''s last run, its note and whether it failed');

select pg_temp.lw_assert((select (j -> 'ci-lw-spc' ->> 'products')::int = 4
                                 and (j -> 'ci-lw-spc' ->> 'labels_read')::int = 2
                                 and (j -> 'ci-lw-spc' ->> 'lists')::int = 2
                                 and (j -> 'ci-lw-spc' ->> 'lists_broken')::int = 1 from lws),
  'the Sources page counts every ingredient''s products and lists');

-- ───────────── no one outside the team, and never written from the browser ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000009f9","role":"authenticated"}', false);
set role authenticated;
select pg_temp.lw_assert(pg_temp.lw_refused($q$select label_watch('00000000-0000-0000-0000-00000091a001')$q$) like '42501%',
  'someone signed in but not in the team cannot read the label watch');
select pg_temp.lw_assert(pg_temp.lw_refused($q$select label_watch_sources()$q$) like '42501%',
  'nor the Sources page''s counts');
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.lw_assert(pg_temp.lw_refused($q$insert into spc_listing (source_id, ingredient_id, products, complete)
  values ('ci-lw-spc', '00000000-0000-0000-0000-00000091a002', 9, true)$q$) is not null,
  'a list is never written from the browser');
select pg_temp.lw_assert(pg_temp.lw_refused($q$select label_watch_source('ci-lw-spc', null)$q$) is not null,
  'the inner function is not callable from the browser');
reset role;

rollback;
