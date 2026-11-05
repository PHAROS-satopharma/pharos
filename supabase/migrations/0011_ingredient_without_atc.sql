-- PHAROS — saving an ingredient that has no ATC code updates it instead of adding it again (2026-11-05).
--
-- save_ingredient found an existing ingredient only through "on conflict (atc_code)". Two NULLs never
-- conflict, so saving an ingredient without an ATC code a second time (to add a term, say) inserted a
-- second copy of it, and one with a Wikidata id but no ATC code failed on the wikidata_qid key instead.
-- Now the existing ingredient is found first by ATC code, then (when one side has no ATC code) by
-- Wikidata id, then by its English name, and updated; only when none matches is a new one added. Same
-- signature, same grants.

create or replace function save_ingredient(p jsonb) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v_id uuid;
  v_person uuid := my_person_id();
  v_inn text := trim(p->>'inn_en');
  v_atc text := nullif(trim(p->>'atc_code'), '');
  v_qid text := nullif(trim(p->>'wikidata_qid'), '');
  v_rxcui text := nullif(trim(p->>'rxcui'), '');
  t jsonb;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'only an admin can save an ingredient' using errcode = '42501';
  end if;
  if coalesce(v_inn, '') = '' then
    raise exception 'inn_en is required';
  end if;

  select id into v_id from ingredient
   where (v_atc is not null and atc_code = v_atc)
      -- one substance can carry several ATC codes: a match by Wikidata id or name never takes over a
      -- row that has a different ATC code
      or ((v_atc is null or atc_code is null)
          and ((v_qid is not null and wikidata_qid = v_qid) or lower(inn_en) = lower(v_inn)))
   order by (v_atc is not null and atc_code = v_atc) desc,
            (v_qid is not null and wikidata_qid = v_qid) desc,
            created_at
   limit 1
   for update;

  if v_id is null then
    insert into ingredient (inn_en, atc_code, wikidata_qid, rxcui, confirmed_by, confirmed_at)
    values (v_inn, v_atc, v_qid, v_rxcui, v_person, now())
    returning id into v_id;
  else
    update ingredient
       set inn_en = v_inn,
           atc_code = coalesce(v_atc, atc_code),
           wikidata_qid = coalesce(v_qid, wikidata_qid),
           rxcui = coalesce(v_rxcui, rxcui),
           active = true,
           confirmed_by = v_person,
           confirmed_at = now()
     where id = v_id;
  end if;

  for t in select * from jsonb_array_elements(coalesce(p->'terms', '[]'::jsonb)) loop
    continue when coalesce(trim(t->>'term'), '') = '';
    insert into ingredient_term (ingredient_id, lang, country_code, term, kind, mode, exclusions, source,
                                 verified_by, verified_at)
    values (v_id, t->>'lang', nullif(t->>'country_code', ''), trim(t->>'term'),
            coalesce(nullif(t->>'kind', ''), 'inn')::term_kind,
            coalesce(nullif(t->>'mode', ''), 'stem')::match_mode,
            coalesce(array(select jsonb_array_elements_text(t->'exclusions')), '{}'),
            coalesce(nullif(t->>'source', ''), 'manual'), v_person, now())
    on conflict (ingredient_id, lang, term) do update
       set country_code = excluded.country_code, kind = excluded.kind, mode = excluded.mode,
           exclusions = excluded.exclusions, source = excluded.source,
           verified_by = v_person, verified_at = now();
  end loop;

  insert into ingredient_class (ingredient_id, class_id)
  select v_id, c.id from drug_class c
   where c.code in (select jsonb_array_elements_text(coalesce(p->'class_codes', '[]'::jsonb)))
  on conflict do nothing;

  return v_id;
end $$;
