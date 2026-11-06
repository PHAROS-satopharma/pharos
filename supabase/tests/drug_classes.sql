-- PHAROS CI — drug classes from the ATC code and the check of the past (0034). Runs on the database ci.yml
-- prepared: CI Admin (…a1) and CI Reader (…b2) exist.

create function pg_temp.dc_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.dc_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

create function pg_temp.dc_as(p uuid) returns void language sql as $$
  select set_config('request.jwt.claims', jsonb_build_object('sub', p, 'role', 'authenticated')::text, false)
$$;

-- ───────────── the NSAID seed keeps working ─────────────
select pg_temp.dc_assert((select origin = 'hand' and confirmed_at is null from drug_class where code = 'NSAID'),
  'the NSAID class is a hand-made class, not yet confirmed');
select pg_temp.dc_assert((select count(*) > 20 and bool_and(source = 'seed') from class_term ct
                            join drug_class c on c.id = ct.class_id where c.code = 'NSAID'),
  'the NSAID words are all still there, marked as seed words');
select pg_temp.dc_assert((select count(*) = 1 from ingredient_class ic join drug_class c on c.id = ic.class_id
                            join ingredient i on i.id = ic.ingredient_id
                           where c.code = 'NSAID' and i.inn_en = 'lornoxicam'),
  'lornoxicam is still an NSAID');

-- ───────────── changed_at: what makes a word due again ─────────────
insert into ingredient (id, inn_en, atc_code) values ('00000000-0000-0000-0000-0000000dc001', 'ci-levofloxacin', 'J01MA12');
insert into ingredient_term (id, ingredient_id, lang, term)
  values ('00000000-0000-0000-0000-0000000dc011', '00000000-0000-0000-0000-0000000dc001', 'en', 'levofloxacin');
select pg_temp.dc_assert((select changed_at is not null and rematched_at is null from ingredient_term
                           where id = '00000000-0000-0000-0000-0000000dc011'),
  'a new word is due: it has a change time and was never checked against the past');

update ingredient_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00'
 where id = '00000000-0000-0000-0000-0000000dc011';
update ingredient_term set verified_at = now(), country_code = 'FI' where id = '00000000-0000-0000-0000-0000000dc011';
select pg_temp.dc_assert((select changed_at = '2026-01-01 00:00+00' from ingredient_term
                           where id = '00000000-0000-0000-0000-0000000dc011'),
  'verifying a word or giving it a country does not make it due again');
update ingredient_term set exclusions = '{levofloxacinum}' where id = '00000000-0000-0000-0000-0000000dc011';
select pg_temp.dc_assert((select changed_at > rematched_at from ingredient_term
                           where id = '00000000-0000-0000-0000-0000000dc011'),
  'a change to what the word finds (its exclusions) makes it due again');

update ingredient_term set changed_at = '2026-01-01 00:00+00' where id = '00000000-0000-0000-0000-0000000dc011';
update ingredient set active = false where id = '00000000-0000-0000-0000-0000000dc001';
select pg_temp.dc_assert((select changed_at = '2026-01-01 00:00+00' from ingredient_term
                           where id = '00000000-0000-0000-0000-0000000dc011'),
  'pausing an ingredient leaves its words alone');
update ingredient set active = true where id = '00000000-0000-0000-0000-0000000dc001';
select pg_temp.dc_assert((select changed_at > '2026-01-02 00:00+00' from ingredient_term
                           where id = '00000000-0000-0000-0000-0000000dc011'),
  'watching a paused ingredient again makes its words due again');

-- ───────────── a class made from the ATC code, its words, its confirmation ─────────────
insert into drug_class (id, code, name_en, origin, wikidata_qid)
  values ('00000000-0000-0000-0000-0000000dc002', 'J01MA', 'Fluoroquinolones', 'atc', 'Q28801726');
insert into class_term (class_id, lang, term, mode, source)
  values ('00000000-0000-0000-0000-0000000dc002', 'en', 'fluoroquinolone', 'stem', 'wikidata');
select pg_temp.dc_assert(pg_temp.dc_refused($q$insert into drug_class (code, name_en, origin) values ('X1', 'x', 'who')$q$) like '23514%',
  'a class comes from the ATC code or by hand, nothing else');

-- The administrator adds two words (one Japanese), removes one, and confirms the class.
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000a1');
set role authenticated;
select add_class_term('00000000-0000-0000-0000-0000000dc002', ' DE ', '  Fluorchinolon  ') as dc_de \gset
select add_class_term('00000000-0000-0000-0000-0000000dc002', 'ja', 'キノロン系') as dc_ja \gset
select add_class_term('00000000-0000-0000-0000-0000000dc002', 'fr', 'FQ', 'exact') as dc_fr \gset
select pg_temp.dc_refused($q$select add_class_term('00000000-0000-0000-0000-0000000dc002', 'english', 'quinolone')$q$) as dc_badlang \gset
select pg_temp.dc_refused($q$select add_class_term('00000000-0000-0000-0000-0000000dc002', 'en', 'q')$q$) as dc_short \gset
select pg_temp.dc_refused($q$select add_class_term('00000000-0000-0000-0000-0000000dc0ff', 'en', 'quinolone')$q$) as dc_noclass \gset
select remove_class_term(:'dc_fr');
select pg_temp.dc_refused(format('select remove_class_term(%L)', :'dc_fr')) as dc_gone \gset
select confirm_drug_class('00000000-0000-0000-0000-0000000dc002') is not null as dc_confirmed \gset
reset role;

select pg_temp.dc_assert((select lang = 'de' and term = 'Fluorchinolon' and mode = 'stem' and source = 'manual'
                                 and added_by = (select id from person where email = 'admin@example.test')
                                 and rematched_at is null
                            from class_term where id = :'dc_de'),
  'an added word is trimmed, in lower-case language, matched by word start, names who added it, and is due');
select pg_temp.dc_assert((select mode = 'substring' from class_term where id = :'dc_ja'),
  'a Japanese word is matched anywhere in the text');
select pg_temp.dc_assert(not exists (select 1 from class_term where id = :'dc_fr'), 'a removed word is gone');
select pg_temp.dc_assert(:'dc_gone' like 'P0002%', 'removing a word twice says it is no longer there');
select pg_temp.dc_assert(:'dc_badlang' like '22023%' and :'dc_short' like '22023%' and :'dc_noclass' like 'P0002%',
  'a word needs a language, two characters or more, and a class that exists');
select pg_temp.dc_assert(:'dc_confirmed'::boolean
  and (select confirmed_by = (select id from person where email = 'admin@example.test')
              and confirmed_at > now() - interval '1 hour'
         from drug_class where id = '00000000-0000-0000-0000-0000000dc002'),
  'confirming a class records the signed-in administrator and the database time');
select pg_temp.dc_assert((select count(*) >= 2 from audit_log where table_name = 'drug_class'
                           and row_pk = '00000000-0000-0000-0000-0000000dc002'),
  'creating and confirming a class are in the audit log');

-- A reader changes nothing.
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select pg_temp.dc_refused($q$select add_class_term('00000000-0000-0000-0000-0000000dc002', 'en', 'quinolone')$q$) as dc_r_add \gset
select pg_temp.dc_refused(format('select remove_class_term(%L)', :'dc_de')) as dc_r_remove \gset
select pg_temp.dc_refused($q$select confirm_drug_class('00000000-0000-0000-0000-0000000dc002')$q$) as dc_r_confirm \gset
select count(*) as dc_r_terms from class_term where class_id = '00000000-0000-0000-0000-0000000dc002' \gset
reset role;
select pg_temp.dc_assert(:'dc_r_add' like '42501%' and :'dc_r_remove' like '42501%' and :'dc_r_confirm' like '42501%',
  'a reader cannot add, remove or confirm');
select pg_temp.dc_assert(:'dc_r_terms'::int = 3, 'a reader sees the class words');

-- ───────────── the check of the past: one job at a time, read-only in the app ─────────────
insert into rematch_job (since, ingredient_term_ids) values ('2025-11-06', array['00000000-0000-0000-0000-0000000dc011'::uuid]);
select pg_temp.dc_assert(pg_temp.dc_refused($q$insert into rematch_job (since) values ('2025-11-06')$q$) like '23505%',
  'a second check of the past cannot start while one is open');
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select count(*) as dc_jobs from rematch_job \gset
select pg_temp.dc_refused($q$update rematch_job set finished_at = now()$q$) as dc_r_job \gset
reset role;
select pg_temp.dc_assert(:'dc_jobs'::int >= 1 and :'dc_r_job' like '42501%',
  'a signed-in person sees the progress of the check and cannot change it');
update rematch_job set finished_at = now() where finished_at is null;

-- Leave the shared test database as it was.
delete from rematch_job;
delete from drug_class where id = '00000000-0000-0000-0000-0000000dc002';
delete from ingredient where id = '00000000-0000-0000-0000-0000000dc001';
