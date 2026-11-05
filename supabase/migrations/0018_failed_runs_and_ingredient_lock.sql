-- PHAROS — one definition of a failed source run; one ingredient save at a time (2026-11-05).
--
-- 1. source_run.error carries the reason a run failed, but also notes on runs that completed: 'imap not
--    configured', 'imap: …' (held or unreachable mail), 'N item(s) failed; first: …', 'time budget
--    reached: …', and the label watch's 'N error(s); first: …' and 'N product(s) without label text'.
--    The Reports screen counted every note as a failed run, while the monthly PDF/XLSX exempted only
--    'imap not configured', so the two showed different numbers. Both now ask source_run_failed(); the
--    collectors write the notes in collectors/run.py and collectors/spc/run.py (a label-watch run that
--    read no label at all is written 'no label read: …', a failure).
--
-- 2. save_ingredient found an existing ingredient with SELECT … FOR UPDATE and inserted one when none
--    was found. Two saves of the same new ingredient at once both found nothing (FOR UPDATE locks no
--    row that is not there) and both inserted it. A transaction-scoped advisory lock now takes the
--    saves one at a time. Same signatures, same grants (create or replace keeps them).

create or replace function source_run_failed(p_error text) returns boolean
language sql immutable set search_path = public as $$
  select p_error is not null
     and p_error !~ '^(imap not configured|imap: |[0-9]+ item\(s\) failed; first: |time budget reached: |[0-9]+ error\(s\); first: |[0-9]+ product\(s\) without label text)'
$$;

create or replace function monthly_screening_log(p_month date)
returns table (source_id text, regulator text, country text, runs bigint, ok_runs bigint, failed_runs bigint,
               items_seen bigint, items_new bigint, items_matched bigint, last_run timestamptz)
language sql stable security definer set search_path = public as $$
  select s.id, r.name, r.country_name,
         count(sr.id),
         count(sr.id) filter (where not source_run_failed(sr.error)),
         count(sr.id) filter (where source_run_failed(sr.error)),
         coalesce(sum(sr.items_seen), 0), coalesce(sum(sr.items_new), 0), coalesce(sum(sr.items_matched), 0),
         max(sr.started_at)
    from source s
    join regulator r on r.id = s.regulator_id
    left join source_run sr
      on sr.source_id = s.id
     and sr.started_at >= (date_trunc('month', p_month::timestamp) at time zone 'Africa/Cairo')
     and sr.started_at <  ((date_trunc('month', p_month::timestamp) + interval '1 month') at time zone 'Africa/Cairo')
   where my_role() is not null
   group by s.id, r.name, r.country_name
   order by r.country_name, s.id
$$;

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

  -- One save at a time: two saves of the same new ingredient at once (two admins, a double click) would
  -- both find nothing and both insert it. The lock is released when the transaction ends.
  perform pg_advisory_xact_lock(hashtext('pharos.save_ingredient'));

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
