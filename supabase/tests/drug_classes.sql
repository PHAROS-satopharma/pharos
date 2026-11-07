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

-- ───────────── the search profile (0049): the group searched, the parent class off, a group by hand ─────────────
select pg_temp.dc_assert((select ic.relation = 'manual' and ic.enabled from ingredient_class ic
                            join drug_class c on c.id = ic.class_id where c.code = 'NSAID' limit 1),
  'the NSAID seed is a manual group whose words are searched');
insert into ingredient_class (ingredient_id, class_id)
  values ('00000000-0000-0000-0000-0000000dc001', '00000000-0000-0000-0000-0000000dc002');
select pg_temp.dc_assert((select relation = 'group' and enabled from ingredient_class
                           where ingredient_id = '00000000-0000-0000-0000-0000000dc001'
                             and class_id = '00000000-0000-0000-0000-0000000dc002'),
  'a link saved without more is the searched group');
insert into drug_class (id, code, name_en, origin, wikidata_qid)
  values ('00000000-0000-0000-0000-0000000dc003', 'J01M', 'Quinolone antibacterials', 'atc', 'Q13669486');
insert into class_term (id, class_id, lang, term, mode, source)
  values ('00000000-0000-0000-0000-0000000dc031', '00000000-0000-0000-0000-0000000dc003', 'en', 'quinolone antibiotic',
          'stem', 'wikidata');
update class_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00'
 where id = '00000000-0000-0000-0000-0000000dc031';
insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values ('00000000-0000-0000-0000-0000000dc001', '00000000-0000-0000-0000-0000000dc003', 'parent', false);
select pg_temp.dc_assert(pg_temp.dc_refused($q$update ingredient_class set relation = 'cousin'
    where class_id = '00000000-0000-0000-0000-0000000dc003'$q$) like '23514%',
  'a class is the group, the parent class or a manual group, nothing else');
insert into drug_class (id, code, name_en, origin)
  values ('00000000-0000-0000-0000-0000000dc004', 'CI_HAND', 'CI hand class', 'hand');
insert into ingredient_class (ingredient_id, class_id)
  values ('00000000-0000-0000-0000-0000000dc001', '00000000-0000-0000-0000-0000000dc004');
select pg_temp.dc_assert((select relation = 'manual' from ingredient_class
                           where class_id = '00000000-0000-0000-0000-0000000dc004'),
  'a hand-made class linked without more is a manual group');

-- The administrator adds a group by hand, switches the parent class on, and may not remove an ATC class.
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000a1');
set role authenticated;
select add_search_group('00000000-0000-0000-0000-0000000dc001', '  Respiratory   fluoroquinolones ') as dc_grp \gset
select add_search_group('00000000-0000-0000-0000-0000000dc001', 'respiratory FLUOROQUINOLONES') as dc_grp2 \gset
select pg_temp.dc_refused($q$select add_search_group('00000000-0000-0000-0000-0000000dc001', 'J01MA')$q$) as dc_atc \gset
select pg_temp.dc_refused($q$select add_search_group('00000000-0000-0000-0000-0000000dc001', 'x')$q$) as dc_shortname \gset
select pg_temp.dc_refused($q$select add_search_group('00000000-0000-0000-0000-0000000dc0ff', 'Quinolones')$q$) as dc_noing \gset
select add_class_term(:'dc_grp', 'en', 'respiratory fluoroquinolone') as dc_grp_word \gset
select set_class_search('00000000-0000-0000-0000-0000000dc001', '00000000-0000-0000-0000-0000000dc003', true);
select pg_temp.dc_refused($q$select set_class_search('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc0ff', true)$q$) as dc_nolink \gset
select pg_temp.dc_refused($q$select unlink_search_group('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc002')$q$) as dc_unlink_atc \gset
reset role;

select pg_temp.dc_assert(:'dc_grp' = :'dc_grp2'
  and (select origin = 'hand' and name_en = 'Respiratory fluoroquinolones' and code = 'RESPIRATORY_FLUOROQUINOLONES'
         from drug_class where id = :'dc_grp'),
  'a group by hand is a hand-made class named as typed, found again by its name in any case');
select pg_temp.dc_assert((select relation = 'manual' and enabled from ingredient_class
                           where ingredient_id = '00000000-0000-0000-0000-0000000dc001' and class_id = :'dc_grp'),
  'the group by hand is linked as a manual group, searched');
select pg_temp.dc_assert((select source = 'manual' and lang = 'en' from class_term where id = :'dc_grp_word'),
  'its words are added as the words of any class');
select pg_temp.dc_assert(:'dc_atc' like '22023%' and :'dc_shortname' like '22023%' and :'dc_noing' like 'P0002%',
  'an ATC code, a one-letter name and an unknown ingredient are refused');
select pg_temp.dc_assert((select enabled and changed_at > now() - interval '1 hour' from ingredient_class
                           where ingredient_id = '00000000-0000-0000-0000-0000000dc001'
                             and class_id = '00000000-0000-0000-0000-0000000dc003'),
  'the parent class is switched on, and the switch is dated');
select pg_temp.dc_assert((select changed_at > rematched_at from class_term
                           where id = '00000000-0000-0000-0000-0000000dc031'),
  'switching a class on makes its words due for the check of the past again');
select pg_temp.dc_assert(:'dc_nolink' like 'P0002%' and :'dc_unlink_atc' like '22023%',
  'a class that is not linked cannot be switched; a class from the ATC code cannot be removed');
select pg_temp.dc_assert((select count(*) >= 4 from audit_log where table_name = 'ingredient_class'
                           and new_row ->> 'ingredient_id' = '00000000-0000-0000-0000-0000000dc001'),
  'every link and switch is in the audit log');

-- The administrator removes the group by hand; a reader changes nothing.
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000a1');
set role authenticated;
select unlink_search_group('00000000-0000-0000-0000-0000000dc001', :'dc_grp');
select pg_temp.dc_refused(format('select unlink_search_group(%L, %L)', '00000000-0000-0000-0000-0000000dc001', :'dc_grp'))
  as dc_unlinked_twice \gset
reset role;
select pg_temp.dc_assert(not exists (select 1 from ingredient_class where class_id = :'dc_grp')
    and exists (select 1 from drug_class where id = :'dc_grp') and :'dc_unlinked_twice' like 'P0002%',
  'a removed group leaves the ingredient and keeps its class and words; removing it twice says so');
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select pg_temp.dc_refused($q$select set_class_search('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc003', false)$q$) as dc_r_switch \gset
select pg_temp.dc_refused($q$select add_search_group('00000000-0000-0000-0000-0000000dc001', 'Quinolones')$q$) as dc_r_group \gset
select pg_temp.dc_refused($q$select unlink_search_group('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc004')$q$) as dc_r_unlink \gset
select count(*) as dc_r_links from ingredient_class where ingredient_id = '00000000-0000-0000-0000-0000000dc001' \gset
reset role;
select pg_temp.dc_assert(:'dc_r_switch' like '42501%' and :'dc_r_group' like '42501%' and :'dc_r_unlink' like '42501%',
  'a reader cannot switch, add or remove a group');
select pg_temp.dc_assert(:'dc_r_links'::int = 3, 'a reader sees the ingredient''s classes and their switches');

-- ───────────── notices only: a class kept out of the literature search (0051) ─────────────
select pg_temp.dc_assert((select not bool_or(literature) from ingredient_class
                           where ingredient_id = '00000000-0000-0000-0000-0000000dc001'),
  'every link starts out of the literature search: the literature is searched for names (0093)');
update ingredient_class set literature = true
 where ingredient_id = '00000000-0000-0000-0000-0000000dc001' and class_id = '00000000-0000-0000-0000-0000000dc002';
update ingredient_class set changed_at = '2026-01-01 00:00+00'
 where ingredient_id = '00000000-0000-0000-0000-0000000dc001' and class_id = '00000000-0000-0000-0000-0000000dc002';
select coalesce(max(changed_at)::text, 'none') as dc_lit_term_before from class_term
 where class_id = '00000000-0000-0000-0000-0000000dc002' \gset
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000a1');
set role authenticated;
select set_class_literature('00000000-0000-0000-0000-0000000dc001', '00000000-0000-0000-0000-0000000dc002', false);
select pg_temp.dc_refused($q$select set_class_literature('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc0ff', false)$q$) as dc_lit_nolink \gset
select (ingredient_screen('00000000-0000-0000-0000-0000000dc001', current_date - 6, current_date)
          -> 'ingredient' -> 'classes') as dc_lit_screen \gset
reset role;
select pg_temp.dc_assert((select not literature and enabled and changed_at > now() - interval '1 hour'
                            from ingredient_class
                           where ingredient_id = '00000000-0000-0000-0000-0000000dc001'
                             and class_id = '00000000-0000-0000-0000-0000000dc002'),
  'an administrator keeps a class out of the literature: it stays searched in notices, and the switch is dated');
select pg_temp.dc_assert((select coalesce(max(changed_at)::text, 'none') = :'dc_lit_term_before' from class_term
                           where class_id = '00000000-0000-0000-0000-0000000dc002'),
  'keeping a class out of the literature does not make its words due for the check of the past');
select pg_temp.dc_assert(:'dc_lit_nolink' like 'P0002%', 'a class that is not linked cannot be kept out');
select pg_temp.dc_assert((select bool_or(c ->> 'id' = '00000000-0000-0000-0000-0000000dc002'
                                         and (c ->> 'literature')::boolean = false)
                            from jsonb_array_elements(:'dc_lit_screen'::jsonb) c),
  'the Ingredients screen reports the class as notices only');
select pg_temp.dc_assert((select count(*) >= 1 from audit_log where table_name = 'ingredient_class'
                           and new_row ->> 'class_id' = '00000000-0000-0000-0000-0000000dc002'
                           and new_row ->> 'literature' = 'false'),
  'the literature switch is in the audit log');
select pg_temp.dc_as('00000000-0000-0000-0000-0000000000b2');
set role authenticated;
select pg_temp.dc_refused($q$select set_class_literature('00000000-0000-0000-0000-0000000dc001',
    '00000000-0000-0000-0000-0000000dc002', true)$q$) as dc_r_lit \gset
reset role;
select pg_temp.dc_assert(:'dc_r_lit' like '42501%'
    and (select not literature from ingredient_class where ingredient_id = '00000000-0000-0000-0000-0000000dc001'
                                                       and class_id = '00000000-0000-0000-0000-0000000dc002'),
  'a reader cannot put a class back in the literature');

-- Leave the shared test database as it was.
delete from rematch_job;
delete from drug_class where id in ('00000000-0000-0000-0000-0000000dc002', '00000000-0000-0000-0000-0000000dc003',
                                    '00000000-0000-0000-0000-0000000dc004', :'dc_grp');
delete from ingredient where id = '00000000-0000-0000-0000-0000000dc001';
