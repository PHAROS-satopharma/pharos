-- PHAROS CI — any ingredient she adds is covered (0045): ingredient_readiness() and her subscription to every
-- ingredient. Runs on the database ci.yml prepared: CI Admin (…a1, no Telegram), CI Reader (…b2), CI Reviewer
-- (…c3, Telegram) and CI Admin Two (…d4, Telegram) exist. Everything here happens in one transaction that is
-- rolled back at the end, so nothing is left behind.

begin;

create function pg_temp.ir_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ir_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- The readiness of CI readyamine, read as the reader (the screen) and kept for the assertions.
create temp table ir_res (name text primary key, j jsonb);
create function pg_temp.ir_read(which text) returns void language plpgsql as $$
declare
  v jsonb;
begin
  perform set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', true);
  set local role authenticated;
  v := ingredient_readiness('00000000-0000-0000-0000-00000045a001');
  reset role;
  perform set_config('request.jwt.claims', '', true);
  insert into ir_res values (which, v);
end $$;
create function pg_temp.ir(which text) returns jsonb language sql as $$
  select j from ir_res where name = which
$$;

-- ───────────── a new ingredient, just saved: one English name, a class from the ATC code, nothing run yet ─────────────
insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000045a001', 'CI readyamine', 'Z95ZZ01'),
  ('00000000-0000-0000-0000-00000045a002', 'CI otherready', 'Z95ZZ02');
insert into ingredient_term (id, ingredient_id, lang, term) values
  ('00000000-0000-0000-0000-00000045c001', '00000000-0000-0000-0000-00000045a001', 'en', 'CI readyamine');
insert into drug_class (id, code, name_en, origin) values
  ('00000000-0000-0000-0000-00000045d001', 'Z95ZZ', 'CI readyoids', 'atc');
insert into class_term (id, class_id, lang, term) values
  ('00000000-0000-0000-0000-00000045d101', '00000000-0000-0000-0000-00000045d001', 'en', 'ci readyoids'),
  ('00000000-0000-0000-0000-00000045d102', '00000000-0000-0000-0000-00000045d001', 'de', 'CI-Readyoide');
-- the class switched into the literature (off by default since 0093), so its English word is waited for too
insert into ingredient_class (ingredient_id, class_id, literature) values
  ('00000000-0000-0000-0000-00000045a001', '00000000-0000-0000-0000-00000045d001', true);
-- Two countries with a label watch (one of them with a switched-off source too), and their languages.
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-IR-A', 'XR', 'CI Readyland', 'CI Readyland Agency', '{en,de}', 'https://ready.example.test/'),
  ('CI-IR-B', 'XW', 'CI Waitland', 'CI Waitland Agency', '{sv}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-ir-spc-a', 'CI-IR-A', 'spc', 'api', 'https://ready.example.test/spc.json', 'ci', '{en}',
   'https://ready.example.test/products', true),
  ('ci-ir-spc-b', 'CI-IR-B', 'spc', 'api', 'https://wait.example.test/spc.json', 'ci', '{sv}',
   'https://wait.example.test/products', true),
  ('ci-ir-spc-off', 'CI-IR-B', 'spc', 'api', 'https://wait.example.test/old.json', 'ci', '{sv}', null, false);
-- the Europe PMC watch switched off until its own case below (0082): nothing is waited for on it
update source set enabled = false where id = 'europepmc';
-- Her database pages (0095): one read by Readyland's source, one by Waitland's switched-off source only, one by none.
insert into regulator_page (regulator_id, kind, sort, label, url, read_by, partial, note) values
  ('CI-IR-A', 'database', 1, 'CI ready database', 'https://ready.example.test/products', '{ci-ir-spc-a}', false, null),
  ('CI-IR-B', 'database', 1, 'CI old list', 'https://wait.example.test/old', '{ci-ir-spc-off}', false, null),
  ('CI-IR-B', 'database', 2, 'CI register', 'https://wait.example.test/register', '{}', false, 'Not read: a sign-in.');

select pg_temp.ir_read('new');

select pg_temp.ir_assert(not (pg_temp.ir('new') ->> 'ready')::boolean, 'a freshly saved ingredient is not ready');
select pg_temp.ir_assert(
  (pg_temp.ir('new') -> 'names' ->> 'languages_with_a_name')::int = 1
    and (pg_temp.ir('new') -> 'names' ->> 'of')::int >= 4
    and pg_temp.ir('new') -> 'names' -> 'missing' ? 'de'
    and pg_temp.ir('new') -> 'names' -> 'missing' ? 'sv'
    and not pg_temp.ir('new') -> 'names' -> 'missing' ? 'en',
  'names: one language has a name; the regulators'' other languages are missing');
select pg_temp.ir_assert(
  (pg_temp.ir('new') -> 'class' ->> 'atc')::boolean
    and (pg_temp.ir('new') -> 'class' ->> 'classes')::int = 1
    and (pg_temp.ir('new') -> 'class' ->> 'words')::int = 2
    and not (pg_temp.ir('new') -> 'class' ->> 'confirmed')::boolean,
  'class: one class with two words, not confirmed yet');
select pg_temp.ir_assert(
  not (pg_temp.ir('new') -> 'past_check' ->> 'done')::boolean
    and (pg_temp.ir('new') -> 'past_check' ->> 'words_due')::int = 3
    and not (pg_temp.ir('new') -> 'past_check' ->> 'job_running')::boolean,
  'the check of the past: the name and both class words are due, no check is running');
select pg_temp.ir_assert(
  (pg_temp.ir('new') -> 'ncbi' ->> 'searches')::int = 0
    and (pg_temp.ir('new') -> 'ncbi' ->> 'expected')::int = 1
    and not (pg_temp.ir('new') -> 'ncbi' ->> 'look_back_done')::boolean
    and pg_temp.ir('new') -> 'ncbi' -> 'last_run' = 'null'::jsonb,
  'NCBI: one search holds Ready (the name in PubMed, 0092), not run yet');
select pg_temp.ir_assert(
  (pg_temp.ir('new') -> 'label_watch' ->> 'products')::int = 0
    and not (pg_temp.ir('new') -> 'label_watch' ->> 'first_snapshot')::boolean
    and not (pg_temp.ir('new') -> 'label_watch' ->> 'japan_code')::boolean
    and pg_temp.ir('new') -> 'label_watch' -> 'waiting' = '["CI Readyland", "CI Waitland"]'::jsonb
    and pg_temp.ir('new') -> 'label_watch' -> 'empty' = '[]'::jsonb
    and pg_temp.ir('new') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-a' ->> 'country' = 'CI Readyland'
    and (pg_temp.ir('new') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-a' ->> 'products')::int = 0
    and not (pg_temp.ir('new') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-a' ->> 'read')::boolean
    and pg_temp.ir('new') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-off' is null,
  'label watch: no product yet; both countries wait for Monday; a switched-off source is not listed');
select pg_temp.ir_assert(
  not (pg_temp.ir('new') -> 'eurd' ->> 'found')::boolean
    and not (pg_temp.ir('new') -> 'ema_mlm' ->> 'monitored')::boolean,
  'EURD: not found; EMA literature monitoring: not monitored');
select pg_temp.ir_assert(not pg_temp.ir('new') -> 'telegram' -> 'people' ? 'CI Reviewer',
  'Telegram: nobody subscribed to it receives its messages yet');

-- ───────────── the check of the past starts ─────────────
insert into rematch_job (since, ingredient_term_ids) values
  (current_date - 365, array['00000000-0000-0000-0000-00000045c001'::uuid]);
select pg_temp.ir_read('running');
select pg_temp.ir_assert(
  (pg_temp.ir('running') -> 'past_check' ->> 'job_running')::boolean
    and not (pg_temp.ir('running') -> 'past_check' ->> 'done')::boolean,
  'while a check runs, the past is "running", not done');

-- ───────────── everything that follows by itself has run ─────────────
update rematch_job set finished_at = now() where finished_at is null;
update ingredient_term set rematched_at = now() where ingredient_id = '00000000-0000-0000-0000-00000045a001';
update class_term set rematched_at = now() where class_id = '00000000-0000-0000-0000-00000045d001';
-- a German name, and the Japan code (a code is not a name: Japanese does not count as a language with a name)
insert into ingredient_term (id, ingredient_id, lang, term, rematched_at) values
  ('00000000-0000-0000-0000-00000045c002', '00000000-0000-0000-0000-00000045a001', 'de', 'CI Readyamin', now());
insert into ingredient_term (id, ingredient_id, lang, country_code, term, kind, mode, source, rematched_at) values
  ('00000000-0000-0000-0000-00000045c003', '00000000-0000-0000-0000-00000045a001', 'ja', 'JP', '1234567', 'code',
   'exact', 'pmda', now());
-- NCBI: the name's PMC look-back finished; the name's PubMed one and both class words' are still running
insert into literature_search (db, query, kind, look_back_from, history_until, look_back_done_at) values
  ('pubmed', 'ci readyamine', 'name', current_date - 365, current_date, null),
  ('pmc', 'ci readyamine', 'name', current_date - 365, current_date, now()),
  ('pubmed', 'ci readyoids', 'class', current_date - 365, current_date, null),
  ('pmc', 'ci readyoids', 'class', current_date - 365, current_date, null);
-- the label watch read both countries and found one product, with its first snapshot
insert into run (id, trigger) values ('00000000-0000-0000-0000-00000045f001', 'cron');
insert into source_run (run_id, source_id, started_at, error) values
  ('00000000-0000-0000-0000-00000045f001', 'ci-ir-spc-a', now(), null),
  ('00000000-0000-0000-0000-00000045f001', 'ci-ir-spc-b', now(), '1 product(s) without label text');
insert into spc_product (id, ingredient_id, source_id, country_code, national_id, product_name, checked_at) values
  ('00000000-0000-0000-0000-00000045b001', '00000000-0000-0000-0000-00000045a001', 'ci-ir-spc-a', 'XR', 'R-1',
   'CI Readyamine 10 mg', now());
insert into spc_snapshot (spc_product_id, sha256, section_hashes) values
  ('00000000-0000-0000-0000-00000045b001', 'ab', '{}'::jsonb);
-- EMA's lists
insert into eurd_entry (eurd_id, ingredient_id, substance, frequency, dlp, submission_date, generics_psur_required,
                        procedure, list_version, list_date, sha256, r2_key)
  values (9945, '00000000-0000-0000-0000-00000045a001', 'ci readyamine', '7 years', '2031-12-01', '2032-02-29', false,
          'PSUSA/00009945/203112', 'EMA/630645/2012 Rev.165', '2026-10-21', 'ab', 'raw/ab');
insert into mlm_entry (ingredient_id, group_id, group_name, named_group, list_name, sha256, r2_key)
  values ('00000000-0000-0000-0000-00000045a001', 45, 'CI readyamine', true, 'CI list', 'cd', 'raw/cd');
-- who hears of it: the reviewer subscribed to every ingredient (Telegram linked); not the administrator
-- subscribed to every ingredient without Telegram; not the one subscribed to another ingredient only
-- (ci.yml links the administrator's Telegram earlier; here, as the case needs, she has none)
update person set telegram_chat_id = null where email = 'admin@example.test';
insert into subscription (person_id, kind, ingredient_id)
select p.id, 'ingredient', null from person p where p.email = 'reviewer@example.test';
insert into subscription (person_id, kind, ingredient_id)
select p.id, 'ingredient', null from person p where p.email = 'admin@example.test';
insert into subscription (person_id, kind, ingredient_id)
select p.id, 'ingredient', '00000000-0000-0000-0000-00000045a002' from person p where p.email = 'admin2@example.test';
-- the administrator confirmed the class
update drug_class set confirmed_at = now(), confirmed_by = (select id from person where email = 'admin@example.test')
 where id = '00000000-0000-0000-0000-00000045d001';

select pg_temp.ir_read('almost');
select pg_temp.ir_assert(
  not (pg_temp.ir('almost') ->> 'ready')::boolean
    and (pg_temp.ir('almost') -> 'ncbi' ->> 'searches')::int = 1
    and not (pg_temp.ir('almost') -> 'ncbi' ->> 'look_back_done')::boolean
    and (pg_temp.ir('almost') -> 'past_check' ->> 'done')::boolean
    and (pg_temp.ir('almost') -> 'past_check' ->> 'words_due')::int = 0,
  'the name''s PubMed look-back still running keeps it from Ready, though the past is checked');

update literature_search set look_back_done_at = now() where db = 'pubmed' and query = 'ci readyamine';
select pg_temp.ir_read('ready');

select pg_temp.ir_assert((pg_temp.ir('ready') ->> 'ready')::boolean,
  'with the name''s PubMed look-back done, it is Ready while the class words'' look-backs still fill in (0092)');
select pg_temp.ir_assert(
  (pg_temp.ir('ready') -> 'names' ->> 'languages_with_a_name')::int = 2
    and not pg_temp.ir('ready') -> 'names' -> 'missing' ? 'de'
    and pg_temp.ir('ready') -> 'names' -> 'missing' ? 'sv',
  'names: the German name counts, the Japan code does not');
select pg_temp.ir_assert((pg_temp.ir('ready') -> 'class' ->> 'confirmed')::boolean, 'class: confirmed');
select pg_temp.ir_assert(
  (pg_temp.ir('ready') -> 'ncbi' ->> 'searches')::int = 1
    and (pg_temp.ir('ready') -> 'ncbi' ->> 'look_back_done')::boolean
    and (pg_temp.ir('ready') -> 'ncbi' ->> 'last_run') is not null,
  'NCBI: the name''s PubMed search ran and finished its look-back');
select pg_temp.ir_assert(
  (pg_temp.ir('ready') -> 'label_watch' ->> 'products')::int = 1
    and (pg_temp.ir('ready') -> 'label_watch' ->> 'first_snapshot')::boolean
    and (pg_temp.ir('ready') -> 'label_watch' ->> 'japan_code')::boolean
    and pg_temp.ir('ready') -> 'label_watch' -> 'waiting' = '[]'::jsonb
    and pg_temp.ir('ready') -> 'label_watch' -> 'empty' = '["CI Waitland"]'::jsonb
    and (pg_temp.ir('ready') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-a' ->> 'products')::int = 1
    and (pg_temp.ir('ready') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-a' ->> 'read')::boolean
    and (pg_temp.ir('ready') -> 'label_watch' -> 'by_source' -> 'ci-ir-spc-b' ->> 'read')::boolean,
  'label watch: one product with a snapshot; a read that only noted something counts as read; the Japan code is there');

-- the database pages (0095): counted against her whole list, as the screen does
create function pg_temp.ir_pages_without_reader() returns int language sql as $$
  select count(*)::int from regulator_page p
   where p.kind = 'database'
     and not exists (select 1 from source s where s.kind = 'spc' and s.enabled and s.id = any(p.read_by))
$$;
select pg_temp.ir_assert(
  (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'total')::int
      = (select count(*) from regulator_page where kind = 'database')
    and (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'not_read')::int = pg_temp.ir_pages_without_reader()
    and pg_temp.ir('new') -> 'label_watch' -> 'pages' -> 'waiting_pages' ? 'CI Readyland: CI ready database'
    and not pg_temp.ir('new') -> 'label_watch' -> 'pages' -> 'waiting_pages' ? 'CI Waitland: CI old list'
    and (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'read')::int
      + (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'waiting')::int
      + (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'not_read')::int
      = (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'total')::int,
  'pages: a new ingredient waits on its read pages; a page read only by a switched-off source, or by none, is not read');
select pg_temp.ir_assert(
  not pg_temp.ir('ready') -> 'label_watch' -> 'pages' -> 'waiting_pages' ? 'CI Readyland: CI ready database'
    and (pg_temp.ir('ready') -> 'label_watch' -> 'pages' ->> 'read')::int
      = (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'read')::int + 1
    and (pg_temp.ir('ready') -> 'label_watch' -> 'pages' ->> 'not_read')::int
      = (pg_temp.ir('new') -> 'label_watch' -> 'pages' ->> 'not_read')::int,
  'pages: once its source has run and read its labels, the page is read');

-- 0113: a source that ran but has not read every label yet leaves its page "being read", not read (on 9 Nov 2026
-- DailyMed ran, read 0 of its 1,911 labels and counted as read)
insert into spc_product (id, ingredient_id, source_id, country_code, national_id, product_name) values
  ('00000000-0000-0000-0000-00000045b002', '00000000-0000-0000-0000-00000045a001', 'ci-ir-spc-a', 'XR', 'R-2',
   'CI Readyamine 20 mg');
select pg_temp.ir_read('label_unread');
select pg_temp.ir_assert(
  (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'read')::int
      = (pg_temp.ir('ready') -> 'label_watch' -> 'pages' ->> 'read')::int - 1
    and (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'reading')::int = 1
    and (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'labels_unread')::int = 1
    and pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' -> 'reading_pages' ? 'CI Readyland: CI ready database'
    and not pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' -> 'waiting_pages' ? 'CI Readyland: CI ready database'
    and (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'read')::int
      + (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'reading')::int
      + (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'waiting')::int
      + (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'not_read')::int
      = (pg_temp.ir('label_unread') -> 'label_watch' -> 'pages' ->> 'total')::int
    and (pg_temp.ir('label_unread') ->> 'ready')::boolean = (pg_temp.ir('ready') ->> 'ready')::boolean,
  'pages: a source that ran with a label still unread leaves its page being read, with the count; Ready unchanged');
update spc_product set checked_at = now() where id = '00000000-0000-0000-0000-00000045b002';
select pg_temp.ir_read('label_read');
select pg_temp.ir_assert(
  (pg_temp.ir('label_read') -> 'label_watch' -> 'pages' ->> 'read')::int
      = (pg_temp.ir('ready') -> 'label_watch' -> 'pages' ->> 'read')::int
    and (pg_temp.ir('label_read') -> 'label_watch' -> 'pages' ->> 'reading')::int = 0
    and (pg_temp.ir('label_read') -> 'label_watch' -> 'pages' ->> 'labels_unread')::int = 0,
  'pages: once that label is read, the page is read again');
delete from spc_product where id = '00000000-0000-0000-0000-00000045b002';
select pg_temp.ir_assert(
  (pg_temp.ir('ready') -> 'eurd' ->> 'found')::boolean
    and pg_temp.ir('ready') -> 'eurd' ->> 'frequency' = '7 years'
    and pg_temp.ir('ready') -> 'eurd' ->> 'dlp' = '2031-12-01'
    and pg_temp.ir('ready') -> 'eurd' ->> 'next_submission' = '2032-02-29'
    and (pg_temp.ir('ready') -> 'ema_mlm' ->> 'monitored')::boolean,
  'EURD: its row with the data lock point and submission date; monitored by EMA');
select pg_temp.ir_assert(pg_temp.ir('ready') -> 'telegram' -> 'people' = '["CI Reviewer"]'::jsonb,
  'Telegram: only the people with Telegram linked and a subscription covering it (every ingredient, or this one)');

-- ───────────── the class above its group, switched off in its search profile (0049): nothing waits on it ─────────────
insert into drug_class (id, code, name_en, origin) values
  ('00000000-0000-0000-0000-00000045d002', 'Z95Z', 'CI readyparents', 'atc');
insert into class_term (id, class_id, lang, term) values
  ('00000000-0000-0000-0000-00000045d201', '00000000-0000-0000-0000-00000045d002', 'en', 'ci readyparents');
insert into ingredient_class (ingredient_id, class_id, relation, enabled) values
  ('00000000-0000-0000-0000-00000045a001', '00000000-0000-0000-0000-00000045d002', 'parent', false);
select pg_temp.ir_read('parent');
select pg_temp.ir_assert(
  (pg_temp.ir('parent') ->> 'ready')::boolean
    and (pg_temp.ir('parent') -> 'class' ->> 'classes')::int = 2
    and (pg_temp.ir('parent') -> 'class' ->> 'words')::int = 2
    and (pg_temp.ir('parent') -> 'past_check' ->> 'words_due')::int = 0
    and (pg_temp.ir('parent') -> 'europepmc' ->> 'expected')::int = 2,
  'a class switched off is linked but not searched: its words wait for no check of the past and are not searched');

-- ───────────── the Europe PMC watch switched on (0082): its look-back fills in, and holds nothing (0092) ─────────────
insert into source (id, regulator_id, kind, channel, url, parser, languages, enabled) values
  ('europepmc', 'CI-IR-A', 'literature', 'api', 'https://europepmc.example.test/search', 'europepmc', '{en}', true)
  on conflict (id) do update set enabled = true;
insert into literature_search (db, query, kind, look_back_from, history_until, look_back_done_at) values
  ('europepmc', 'ci readyamine', 'name', current_date - 365, current_date, null);
select pg_temp.ir_read('epmc_running');
select pg_temp.ir_assert(
  (pg_temp.ir('epmc_running') ->> 'ready')::boolean
    and (pg_temp.ir('epmc_running') -> 'europepmc' ->> 'watched')::boolean
    and not (pg_temp.ir('epmc_running') -> 'europepmc' ->> 'holds_ready')::boolean
    and (pg_temp.ir('epmc_running') -> 'europepmc' ->> 'searches')::int = 1
    and (pg_temp.ir('epmc_running') -> 'europepmc' ->> 'expected')::int = 2
    and not (pg_temp.ir('epmc_running') -> 'europepmc' ->> 'look_back_done')::boolean,
  'Europe PMC switched on, its look-back still running: still Ready, and it says it holds nothing');

-- the name's PubMed look-back started again (a changed name): Ready waits for it once more
update literature_search set look_back_done_at = null where db = 'pubmed' and query = 'ci readyamine';
select pg_temp.ir_read('pubmed_again');
select pg_temp.ir_assert(not (pg_temp.ir('pubmed_again') ->> 'ready')::boolean,
  'the name''s PubMed look-back unfinished again: not Ready');
update literature_search set look_back_done_at = now() where db = 'pubmed' and query = 'ci readyamine';

-- ───────────── the label watch answered, and found nothing: still ready; a country not yet read: not ─────────────
delete from spc_product where id = '00000000-0000-0000-0000-00000045b001';
select pg_temp.ir_read('nolabel');
select pg_temp.ir_assert(
  (pg_temp.ir('nolabel') ->> 'ready')::boolean
    and (pg_temp.ir('nolabel') -> 'label_watch' ->> 'products')::int = 0
    and pg_temp.ir('nolabel') -> 'label_watch' -> 'empty' = '["CI Readyland", "CI Waitland"]'::jsonb,
  'no label in any watched country is an answer, not something still running');
delete from source_run where source_id = 'ci-ir-spc-b';
select pg_temp.ir_read('waiting');
select pg_temp.ir_assert(
  not (pg_temp.ir('waiting') ->> 'ready')::boolean
    and pg_temp.ir('waiting') -> 'label_watch' -> 'waiting' = '["CI Waitland"]'::jsonb,
  'a country whose label watch has not run since the ingredient was added is still waited for, by name');

-- ───────────── an ingredient without an ATC code needs no class ─────────────
update ingredient set atc_code = null where id = '00000000-0000-0000-0000-00000045a001';
delete from ingredient_class where ingredient_id = '00000000-0000-0000-0000-00000045a001';
insert into source_run (run_id, source_id, started_at, error) values
  ('00000000-0000-0000-0000-00000045f001', 'ci-ir-spc-b', now(), null);
select pg_temp.ir_read('noatc');
select pg_temp.ir_assert(
  (pg_temp.ir('noatc') ->> 'ready')::boolean
    and not (pg_temp.ir('noatc') -> 'class' ->> 'atc')::boolean
    and (pg_temp.ir('noatc') -> 'class' ->> 'classes')::int = 0
    and (pg_temp.ir('noatc') -> 'ncbi' ->> 'expected')::int = 1
    and (pg_temp.ir('noatc') -> 'europepmc' ->> 'expected')::int = 1,
  'without an ATC code there is no class to wait for, and only the name is searched');

-- ───────────── who may ask ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ir_refused($q$select ingredient_readiness('00000000-0000-0000-0000-00000045a001')$q$) as ir_stranger \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ir_refused($q$select ingredient_readiness('00000000-0000-0000-0000-0000004500ff')$q$) as ir_unknown \gset
reset role;
select pg_temp.ir_assert(:'ir_stranger' like '42501%', 'someone signed in but not on the team is refused');
select pg_temp.ir_assert(:'ir_unknown' like 'P0002%', 'an unknown ingredient is refused');
select pg_temp.ir_assert(
  not has_function_privilege('anon', 'public.ingredient_readiness(uuid)', 'execute')
    and has_function_privilege('authenticated', 'public.ingredient_readiness(uuid)', 'execute'),
  'signed-out visitors cannot call it; the team can');
-- the report connects as the owner with no sign-in token: it reads the same answer
select set_config('request.jwt.claims', '', false);
select pg_temp.ir_assert((ingredient_readiness('00000000-0000-0000-0000-00000045a001') ->> 'ready')::boolean,
  'the weekly report (a direct connection) reads the readiness');

-- ───────────── her subscription: every ingredient, once, by her address ─────────────
insert into auth.users (id, email) values ('00000000-0000-0000-0000-0000000045e1', 'Sama.Mosaad@satopharma.com');
insert into person (auth_user_id, full_name, email, role) values
  ('00000000-0000-0000-0000-0000000045e1', 'CI Sama', 'Sama.Mosaad@satopharma.com', 'admin');
\i supabase/migrations/0045_ingredient_readiness.sql
\i supabase/migrations/0045_ingredient_readiness.sql
select pg_temp.ir_assert(
  (select count(*) from subscription s join person p on p.id = s.person_id
    where lower(p.email) = 'sama.mosaad@satopharma.com' and s.kind = 'ingredient' and s.ingredient_id is null) = 1,
  'her subscription to every ingredient is added once, whatever the case of her address, and never twice');
select pg_temp.ir_assert(
  (select count(*) from subscription s join person p on p.id = s.person_id
    where p.email = 'reader@example.test' and s.kind = 'ingredient') = 0,
  'nobody else is subscribed by the migration');

rollback;
