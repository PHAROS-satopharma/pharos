-- PHAROS — names that belong to another substance are removed, with what they found (2026-11-06).
--
-- The ingredient lookup proposed Wikidata and PubChem names without checking that they name the same substance.
-- An audit on 6 November 2026 found:
--   levofloxacin   Ofloxacin, Floxin (an ofloxacin brand), Floxacin (a disambiguation page): the EMA PSUSA
--                  "ofloxacin (systemic use)" was linked to levofloxacin. Decided: not linked.
--   guaifenesin    ペントキシベリン (pentoxyverine), Buchenteer (beech tar), C10H14O4 (a formula)
--   paracetamol    "Canada og Japan", "acetaminophen i USA" (pieces of a Norwegian alias)
--   phenylephrine  C9H13NO2 (a formula several substances share)
-- And one near-spelling hit of a code: ivabradine's Japan code 2190039 "possibly" found the number 21900 in
-- Austria's "CHMP Meeting Highlights Juli 2026" (codes are no longer near-spelt, collectors/matching.py).
--
-- Removed here: those names, their match rows, and the ingredient each match gave an issue when nothing else
-- in the issue's notices names that ingredient. An issue left naming no ingredient (and not a class issue) is
-- removed; its notices stay stored. An issue someone has reviewed, sent, put in a signal or an authority
-- report keeps everything and is only named in a notice. ingredient_term, issue_ingredient and issue_document
-- are logged by their audit triggers (0001); the match and issue rows are logged here.
-- The lookup now refuses such names (supabase/functions/ingredient-lookup/guard.ts).

create temp table wrong_term as
select t.*
  from ingredient_term t join ingredient i on i.id = t.ingredient_id
 where (lower(i.inn_en), lower(t.term)) in (
         ('levofloxacin', 'ofloxacin'), ('levofloxacin', 'floxin'), ('levofloxacin', 'floxacin'),
         ('guaifenesin', 'ペントキシベリン'), ('guaifenesin', 'buchenteer'), ('guaifenesin', 'c10h14o4'),
         ('paracetamol', 'canada og japan'), ('paracetamol', 'acetaminophen i usa'),
         ('phenylephrine', 'c9h13no2'));

create temp table wrong_match as
select m.*
  from match m
 where m.term_id in (select id from wrong_term)
    or (m.confidence = 'possible' and m.term_id in (select id from ingredient_term where kind = 'code'));

-- the (issue, ingredient) links these matches made
create temp table lost_link as
select distinct idd.issue_id, wm.ingredient_id
  from wrong_match wm
  join issue_document idd on idd.document_id = wm.document_id and idd.method <> 'suggested'
  join issue i on i.id = idd.issue_id
 where wm.ingredient_id is not null and not i.class_only;

insert into audit_log (table_name, row_pk, action, old_row, new_row, actor)
select 'match', wm.id::text, 'DELETE', to_jsonb(wm), null, null from wrong_match wm;
delete from match where id in (select id from wrong_match);

-- a link another notice of the issue still supports stays
delete from lost_link l
 where exists (select 1 from match m
                 join issue_document idd on idd.document_id = m.document_id and idd.method <> 'suggested'
                where idd.issue_id = l.issue_id and m.ingredient_id = l.ingredient_id);

-- an issue that people have acted on is left as it is
create temp table kept_issue as
select distinct l.issue_id from lost_link l
 where exists (select 1 from review_event r where r.issue_id = l.issue_id)
    or exists (select 1 from notification n where n.issue_id = l.issue_id)
    or exists (select 1 from signal_issue s where s.issue_id = l.issue_id)
    or exists (select 1 from authority_report a where a.issue_id = l.issue_id)
    or exists (select 1 from spc_change c where c.issue_id = l.issue_id)
    or exists (select 1 from issue i where i.id = l.issue_id and i.status <> 'new');
delete from lost_link where issue_id in (select issue_id from kept_issue);

do $$
declare n int;
begin
  select count(*) into n from kept_issue;
  if n > 0 then
    raise notice 'kept as they are (someone acted on them): %',
      (select string_agg(i.title, '; ') from issue i where i.id in (select issue_id from kept_issue));
  end if;
end $$;

delete from issue_ingredient ii
 using lost_link l
 where ii.issue_id = l.issue_id and ii.ingredient_id = l.ingredient_id;

create temp table empty_issue as
select i.*
  from issue i
 where i.id in (select issue_id from lost_link)
   and not i.class_only
   and not exists (select 1 from issue_ingredient ii where ii.issue_id = i.id);

insert into audit_log (table_name, row_pk, action, old_row, new_row, actor)
select 'issue', e.id::text, 'DELETE', to_jsonb(e), null, null from empty_issue e;
delete from issue where id in (select id from empty_issue);

delete from ingredient_term where id in (select id from wrong_term);

drop table wrong_term, wrong_match, lost_link, kept_issue, empty_issue;
