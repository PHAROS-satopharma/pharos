-- PHAROS — app functions that must happen in one step, plus the admin write policy for regulators.
-- Plain Postgres (applies on postgres:16 in CI with the auth stub, and on Supabase).

-- Admins may add a regulator when they add a source for a country PHAROS does not know yet.
create policy regulator_admin on regulator for all to authenticated
  using (my_role() = 'admin') with check (my_role() = 'admin');

-- Save a confirmed ingredient and its terms atomically (admin only).
-- p = {inn_en, atc_code, wikidata_qid, rxcui, class_codes:[..],
--      terms:[{lang, country_code, term, kind, mode, exclusions:[..], source}]}
create or replace function save_ingredient(p jsonb) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v_id uuid;
  v_person uuid := my_person_id();
  t jsonb;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'only an admin can save an ingredient' using errcode = '42501';
  end if;
  if coalesce(trim(p->>'inn_en'), '') = '' then
    raise exception 'inn_en is required';
  end if;

  insert into ingredient (inn_en, atc_code, wikidata_qid, rxcui, confirmed_by, confirmed_at)
  values (trim(p->>'inn_en'), nullif(trim(p->>'atc_code'), ''), nullif(p->>'wikidata_qid', ''),
          nullif(p->>'rxcui', ''), v_person, now())
  on conflict (atc_code) do update
     set inn_en = excluded.inn_en,
         wikidata_qid = coalesce(excluded.wikidata_qid, ingredient.wikidata_qid),
         rxcui = coalesce(excluded.rxcui, ingredient.rxcui),
         active = true,
         confirmed_by = v_person,
         confirmed_at = now()
  returning id into v_id;

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

-- Split a copy out of an issue into an issue of its own (reviewers and admins). The anchor cannot be split.
create or replace function split_issue_document(p_issue uuid, p_document uuid) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v_new uuid;
  v_link link_kind;
  d record;
  i record;
begin
  if my_role() not in ('admin','reviewer') or my_role() is null then
    raise exception 'only a reviewer or admin can split' using errcode = '42501';
  end if;
  select link into v_link from issue_document where issue_id = p_issue and document_id = p_document;
  if v_link is null then raise exception 'that document is not part of this issue'; end if;
  if v_link = 'anchor' then raise exception 'the anchor document cannot be split from its own issue'; end if;

  select * into d from document where id = p_document;
  select * into i from issue where id = p_issue;

  insert into issue (doc_type, title, anchor_document_id, first_date, class_only, is_backfill)
  values (d.doc_type, d.title_orig, d.id, d.published_date, i.class_only, d.is_backfill)
  returning id into v_new;

  delete from issue_document where issue_id = p_issue and document_id = p_document;
  insert into issue_document (issue_id, document_id, link, method, linked_by)
  values (v_new, p_document, 'anchor', 'manual', my_person_id());

  insert into issue_ingredient (issue_id, ingredient_id)
  select distinct v_new, m.ingredient_id from match m
   where m.document_id = p_document and m.ingredient_id is not null
  on conflict do nothing;

  return v_new;
end $$;

-- Per-source screening log for one month (the Reports screen), counted in the database.
create or replace function monthly_screening_log(p_month date)
returns table (source_id text, regulator text, country text, runs bigint, ok_runs bigint, failed_runs bigint,
               items_seen bigint, items_new bigint, items_matched bigint, last_run timestamptz)
language sql stable security definer set search_path = public as $$
  select s.id, r.name, r.country_name,
         count(sr.id),
         count(sr.id) filter (where sr.error is null),
         count(sr.id) filter (where sr.error is not null),
         coalesce(sum(sr.items_seen), 0), coalesce(sum(sr.items_new), 0), coalesce(sum(sr.items_matched), 0),
         max(sr.started_at)
    from source s
    join regulator r on r.id = s.regulator_id
    left join source_run sr
      on sr.source_id = s.id
     and sr.started_at >= (date_trunc('month', p_month) at time zone 'Africa/Cairo')
     and sr.started_at <  ((date_trunc('month', p_month) + interval '1 month') at time zone 'Africa/Cairo')
   where my_role() is not null
   group by s.id, r.name, r.country_name
   order by r.country_name, s.id
$$;

revoke all on function save_ingredient(jsonb), split_issue_document(uuid, uuid), monthly_screening_log(date)
  from public, anon;
grant execute on function save_ingredient(jsonb), split_issue_document(uuid, uuid), monthly_screening_log(date)
  to authenticated;
