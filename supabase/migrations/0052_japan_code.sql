-- PHAROS — the Japan code of an ingredient that already exists (2026-11-06, a follow-up to 0045).
--
-- Japan's label watch finds an ingredient's package inserts from its PMDA 一般名 code, kept as an ingredient_term
-- of kind 'code', lang 'ja', country 'JP', mode 'exact', source 'pmda' (0013, collectors/spc/pmda_pi.py). The
-- term editor offered the field only when an ingredient was added, so an ingredient already on the watchlist
-- (levofloxacin) could not get one, while its row said "No Japan code yet". save_ingredient cannot give it one:
-- it also re-confirms the ingredient and only ever adds terms, so a wrong code could not be replaced.
--
-- set_japan_code(p_ingredient, p_code): administrators only, as save_ingredient and the ingredient_term policy
-- (0001, 0004, 0018). The code is checked by the rule of isJapanCode (web/src/features/ingredients/readiness.ts)
-- after trimming and upper-casing: 7 characters (4 digits, then 3 digits or capitals), or the 12-character YJ
-- code that starts with them. The 7 characters are stored. It replaces the ingredient's previous Japan code and
-- touches no other term. Every insert and delete is in audit_log (the audit_ingredient_term trigger, 0001), and
-- a new code is due for the check of the past (term_changed_at, 0034); the same code saved again is not.

create function set_japan_code(p_ingredient uuid, p_code text) returns text
language plpgsql security definer set search_path = public as $$
declare
  v_in     text := upper(btrim(coalesce(p_code, '')));
  v_code   text;
  v_person uuid := my_person_id();
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can set the Japan code.' using errcode = '42501';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
  if v_in !~ '^[0-9]{4}[0-9A-Z]{3}([0-9A-Z]{5})?$' then
    raise exception 'A Japan code has 7 characters (for example 1149036), or 12 for the YJ code that starts with them.'
      using errcode = '22023';
  end if;
  v_code := left(v_in, 7);

  -- One Japan code per ingredient: the previous one goes, unless it is the same code.
  delete from ingredient_term
   where ingredient_id = p_ingredient and kind = 'code' and country_code = 'JP' and term <> v_code;

  insert into ingredient_term (ingredient_id, lang, country_code, term, kind, mode, source, verified_by, verified_at)
  values (p_ingredient, 'ja', 'JP', v_code, 'code', 'exact', 'pmda', v_person, now())
  on conflict (ingredient_id, lang, term) do update
     set country_code = 'JP', kind = 'code', mode = 'exact', source = 'pmda',
         verified_by = v_person, verified_at = now();
  return v_code;
end $$;

revoke all on function set_japan_code(uuid, text) from public, anon;
grant execute on function set_japan_code(uuid, text) to authenticated;
