-- PHAROS — a class's words are checked against the past for an ingredient that joins the class (2026-11-06,
-- finding 4 of the review of the night's changes).
--
-- The check of the past (collectors/rematch.py) takes the words that are due: changed_at newer than
-- rematched_at (0034). Watching a paused ingredient again made only its own words due (ingredient_watched_again,
-- 0034), and linking an ingredient to a class that already had words made nothing due. A class's words are
-- looked for only while an active ingredient searches the class (Store.load_terms), so notices that arrived
-- while the class was searched by no one were never matched by its words.
--
-- Now both make the class's words due: watching an ingredient again (for each class it searches, enabled), and
-- a new searched link of a watched ingredient (any path: save_ingredient, link_ingredient_class, the ATC
-- classes, add_search_group). A link saved switched off (a parent class) waits for set_class_search, which
-- class_search_enabled_again (0049) already dates. The check itself also adds the ingredient to the class-only
-- issues the class's words had already found (collectors/rematch.py, class_gap).

create or replace function ingredient_watched_again() returns trigger language plpgsql set search_path = public as $$
begin
  if new.active and not old.active then
    update ingredient_term set changed_at = now() where ingredient_id = new.id;
    update class_term set changed_at = now()
     where class_id in (select ic.class_id from ingredient_class ic where ic.ingredient_id = new.id and ic.enabled);
  end if;
  return new;
end $$;

create function class_linked() returns trigger language plpgsql set search_path = public as $$
begin
  if new.enabled and exists (select 1 from ingredient i where i.id = new.ingredient_id and i.active) then
    update class_term set changed_at = now() where class_id = new.class_id;
  end if;
  return new;
end $$;
create trigger class_linked after insert on ingredient_class
  for each row execute function class_linked();

-- Once, on deploy: the classes a watched ingredient joined after their words were last checked (an ingredient
-- added since, linked to a class that already had words) get their words checked against the past again.
update class_term ct set changed_at = now()
 where ct.rematched_at is not null
   and exists (select 1 from ingredient_class ic join ingredient i on i.id = ic.ingredient_id
                where ic.class_id = ct.class_id and ic.enabled and i.active and i.created_at > ct.rematched_at);
