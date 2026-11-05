-- PHAROS — "Test against archive" counts notices, and reads their titles and data too (launch check,
-- 2026-11-05).
--
-- The test read only document_text, the full text kept for matched notices. A PubMed record has none (it
-- is matched on its title and its abstract data), so "lornoxicam" found 2 archived texts while 16
-- notices name it: 15 PubMed records and one EMA PSUSA page whose page and attachment were counted as
-- two. It now counts each notice once when its title, any text value of its structured data, or any of
-- its kept texts contains the term, in the language picked (or every language). Same signature, same
-- grants; create or replace keeps the owner, grants and revokes.

create or replace function archive_hit_count(p_term text, p_lang text default null) returns int
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  v_term     text := btrim(coalesce(p_term, ''));
  v_lang     text := nullif(lower(btrim(coalesce(p_lang, ''))), '');
  v_pattern  text;
  v_count    int := 0;
  v_rows     int := 0;
  v_started  timestamptz := clock_timestamp();
  r          record;
begin
  if my_role() is null then
    raise exception 'Sign in to test a term against the archive.' using errcode = '42501';
  end if;
  if char_length(v_term) < 2 or char_length(v_term) > 200 then
    raise exception 'The term must be 2 to 200 characters long.' using errcode = '22023';
  end if;

  -- The term is literal text: escape the LIKE wildcards.
  v_pattern := '%' || replace(replace(replace(v_term, '\', '\'), '%', '\%'), '_', '\_') || '%';

  for r in
    select d.id, d.title_orig, d.structured
      from document d
     where v_lang is null
        or lower(d.lang) = v_lang
        or lower(d.lang) like v_lang || '-%'
  loop
    v_rows := v_rows + 1;
    if coalesce(r.title_orig, '') ilike v_pattern
       or (r.structured is not null and exists (
             select 1 from jsonb_path_query(r.structured, 'strict $.** ? (@.type() == "string")') v
              where (v #>> '{}') ilike v_pattern))
       or exists (select 1 from document_text dt where dt.document_id = r.id and dt.text ilike v_pattern)
    then
      v_count := v_count + 1;
      exit when v_count >= 10000;
    end if;
    if v_rows % 25 = 0 and clock_timestamp() - v_started > interval '4 seconds' then
      raise exception 'The archive test took too long. Try a longer term or pick one language.'
        using errcode = '57014';
    end if;
  end loop;

  return v_count;
end $$;
