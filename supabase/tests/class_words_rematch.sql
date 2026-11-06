-- PHAROS CI — a class's words become due for the check of the past when an ingredient joins the class (0055).
-- Runs on the database ci.yml prepared.

create function pg_temp.cw_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- One class with one word, checked on 1 January; three ingredients.
insert into drug_class (id, code, name_en, origin)
  values ('00000000-0000-0000-0000-00000000ce01', 'CI_CW', 'CI class words', 'hand'),
         ('00000000-0000-0000-0000-00000000ce02', 'CI_CW_OFF', 'CI class switched off', 'hand');
insert into class_term (id, class_id, lang, term, mode, source)
  values ('00000000-0000-0000-0000-00000000ce11', '00000000-0000-0000-0000-00000000ce01', 'en', 'ci class word',
          'stem', 'manual'),
         ('00000000-0000-0000-0000-00000000ce12', '00000000-0000-0000-0000-00000000ce02', 'en', 'ci off word',
          'stem', 'manual');
insert into ingredient (id, inn_en, active)
  values ('00000000-0000-0000-0000-00000000ce21', 'ci-cw-watched', true),
         ('00000000-0000-0000-0000-00000000ce22', 'ci-cw-paused', false),
         ('00000000-0000-0000-0000-00000000ce23', 'ci-cw-parent', true);

create function pg_temp.cw_checked() returns void language sql as $$
  update class_term set changed_at = '2026-01-01 00:00+00', rematched_at = '2026-01-01 00:00+00'
   where id in ('00000000-0000-0000-0000-00000000ce11', '00000000-0000-0000-0000-00000000ce12')
$$;
create function pg_temp.cw_due(p uuid) returns boolean language sql as $$
  select changed_at > rematched_at from class_term where id = p
$$;

select pg_temp.cw_checked();
insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values ('00000000-0000-0000-0000-00000000ce22', '00000000-0000-0000-0000-00000000ce01', 'manual', true);
select pg_temp.cw_assert(not pg_temp.cw_due('00000000-0000-0000-0000-00000000ce11'),
  'linking a paused ingredient to a class leaves its words alone');

insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values ('00000000-0000-0000-0000-00000000ce23', '00000000-0000-0000-0000-00000000ce01', 'parent', false);
select pg_temp.cw_assert(not pg_temp.cw_due('00000000-0000-0000-0000-00000000ce11'),
  'a link saved switched off (a parent class) leaves its words alone');

insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values ('00000000-0000-0000-0000-00000000ce21', '00000000-0000-0000-0000-00000000ce01', 'manual', true);
select pg_temp.cw_assert(pg_temp.cw_due('00000000-0000-0000-0000-00000000ce11'),
  'linking a watched ingredient to a class that already has words makes those words due');

select pg_temp.cw_checked();
insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values ('00000000-0000-0000-0000-00000000ce22', '00000000-0000-0000-0000-00000000ce02', 'parent', false);
update ingredient set active = true where id = '00000000-0000-0000-0000-00000000ce22';
select pg_temp.cw_assert(pg_temp.cw_due('00000000-0000-0000-0000-00000000ce11'),
  'watching a paused ingredient again makes the words of the classes it searches due');
select pg_temp.cw_assert(not pg_temp.cw_due('00000000-0000-0000-0000-00000000ce12'),
  'a class it does not search (switched off) stays as it was');

select pg_temp.cw_checked();
update ingredient set active = false where id = '00000000-0000-0000-0000-00000000ce22';
select pg_temp.cw_assert(not pg_temp.cw_due('00000000-0000-0000-0000-00000000ce11'),
  'pausing an ingredient leaves its classes'' words alone');

-- Leave the shared test database as it was.
delete from drug_class where id in ('00000000-0000-0000-0000-00000000ce01', '00000000-0000-0000-0000-00000000ce02');
delete from ingredient where id in ('00000000-0000-0000-0000-00000000ce21', '00000000-0000-0000-0000-00000000ce22',
                                    '00000000-0000-0000-0000-00000000ce23');
