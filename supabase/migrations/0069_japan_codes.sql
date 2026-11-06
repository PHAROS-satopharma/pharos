-- PHAROS — several Japan codes for one ingredient (2026-11-06, a follow-up to 0052).
--
-- PMDA files one ingredient under one 一般名 code per form: paracetamol (アセトアミノフェン) is 1141007 for the
-- tablets and powders, 1141700 for the suppositories and 1141400 for the injection. Japan's label watch already
-- reads every code an ingredient has (collectors/spc/pmda_pi.py, SQL_TERM_CODES), but set_japan_code() (0052) kept
-- one code per ingredient, so the suppositories and the injection were not watched.
--
-- set_japan_codes(p_ingredient, p_codes): administrators only, as set_japan_code. Every code is checked by the rule
-- of isJapanCode (web/src/features/ingredients/readiness.ts) after trimming and upper-casing; one wrong code refuses
-- the whole list, naming it. A YJ code is stored as the 7 characters it starts with, and a repeated code once. An
-- empty list is refused: it would remove every code. The list replaces the ingredient's Japan codes: a code left
-- off it is removed, a code it already had keeps its row (and is not due again for the check of the past, 0034),
-- a new one is added. Every insert and delete is in audit_log (the audit_ingredient_term trigger, 0001). It touches
-- no other term. set_japan_code() keeps its meaning (the one code given, the others removed).

create function set_japan_codes(p_ingredient uuid, p_codes text[]) returns text[]
language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := my_person_id();
  v_in     text;
  v_codes  text[] := '{}';
  v_wrong  text[] := '{}';
  v_code   text;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can set the Japan codes.' using errcode = '42501';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;

  foreach v_in in array coalesce(p_codes, '{}') loop
    v_in := upper(btrim(coalesce(v_in, '')));
    continue when v_in = '';
    if v_in !~ '^[0-9]{4}[0-9A-Z]{3}([0-9A-Z]{5})?$' then
      v_wrong := v_wrong || v_in;
    elsif not left(v_in, 7) = any (v_codes) then
      v_codes := v_codes || left(v_in, 7);
    end if;
  end loop;
  if cardinality(v_wrong) > 0 then
    raise exception 'Not a Japan code: %. A Japan code has 7 characters (for example 1149036), or 12 for the YJ code that starts with them.',
      array_to_string(v_wrong, ', ') using errcode = '22023';
  end if;
  if cardinality(v_codes) = 0 then
    raise exception 'Give at least one Japan code. A Japan code has 7 characters (for example 1149036), or 12 for the YJ code that starts with them.'
      using errcode = '22023';
  end if;

  delete from ingredient_term
   where ingredient_id = p_ingredient and kind = 'code' and country_code = 'JP' and not term = any (v_codes);

  foreach v_code in array v_codes loop
    insert into ingredient_term (ingredient_id, lang, country_code, term, kind, mode, source, verified_by, verified_at)
    values (p_ingredient, 'ja', 'JP', v_code, 'code', 'exact', 'pmda', v_person, now())
    on conflict (ingredient_id, lang, term) do update
       set country_code = 'JP', kind = 'code', mode = 'exact', source = 'pmda',
           verified_by = v_person, verified_at = now();
  end loop;

  return (select array_agg(c order by c) from unnest(v_codes) c);
end $$;

revoke all on function set_japan_codes(uuid, text[]) from public, anon;
grant execute on function set_japan_codes(uuid, text[]) to authenticated;
