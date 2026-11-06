-- PHAROS — the search profile of an ingredient: its pharmacotherapeutic groups, each searched or not
-- (2026-11-06, after the review of the Ingredients module).
--
-- An ingredient is looked for under its own names and under the words of the drug classes it belongs to. The
-- link between an ingredient and a class now says what the class is to the ingredient, and whether its words
-- are searched:
--   relation  'group'  — its ATC level-4 group (levofloxacin J01MA12 → J01MA Fluoroquinolones): on from the start.
--             'parent' — the level-3 class above it (J01M Quinolone antibacterials): made and shown by the
--                        daily run, but OFF until an administrator has read its words. A wide class's words
--                        from Wikidata carry noise, and each English word costs a 12-month look-back on PubMed
--                        and PubMed Central.
--             'manual' — a group an administrator gave the ingredient by hand (the NSAID seed, add_search_group).
--   enabled   whether the class's words are looked for: in notices (Store.load_terms), in the literature
--             (collectors/parsers/pubmed.py, literature-search) and by the check of the past.
-- Nothing changes for what is there: every link becomes 'group', on; the NSAID seed's link 'manual', on.
-- The search profile shown in the app is derived, never stored: no class on → "Ingredient only"; every class
-- on → "Ingredient + groups"; some on → "Custom".
-- How a document was found is told apart: ingredient_match_relation() answers 'name' (one of the ingredient's
-- own names), 'group', 'manual' or 'parent' (the nearest class first), and ingredient_screen() says it on each
-- mention, with the class's name. by_class stays for the code that reads it.

-- ───────────────────────────── the link ─────────────────────────────
alter table ingredient_class
  add column relation    text not null default 'group' check (relation in ('group', 'parent', 'manual')),
  add column enabled     boolean not null default true,
  add column changed_at  timestamptz not null default now();
update ingredient_class ic set relation = 'manual'
  from drug_class c where c.id = ic.class_id and c.origin = 'hand';

create trigger audit_ingredient_class after insert or update or delete on ingredient_class
  for each row execute function audit_row();

-- A link saved without saying what the class is (save_ingredient's class_codes, link_ingredient_class) takes it
-- from the class: a hand-made class is a manual group. Switching the words on or off is dated.
create function ingredient_class_relation() returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' and new.relation = 'group'
     and exists (select 1 from drug_class c where c.id = new.class_id and c.origin = 'hand') then
    new.relation := 'manual';
  end if;
  if tg_op = 'UPDATE' and new.enabled is distinct from old.enabled then
    new.changed_at := now();
  end if;
  return new;
end $$;
create trigger ingredient_class_relation before insert or update on ingredient_class
  for each row execute function ingredient_class_relation();

-- A class switched on again was not looked for while off: its words are due for the check of the past again
-- (as ingredient_watched_again in 0034 does for an ingredient watched again).
create function class_search_enabled_again() returns trigger language plpgsql set search_path = public as $$
begin
  if new.enabled and not old.enabled then
    update class_term set changed_at = now() where class_id = new.class_id;
  end if;
  return new;
end $$;
create trigger class_search_enabled_again after update of enabled on ingredient_class
  for each row execute function class_search_enabled_again();

-- ───────────────────────────── administrators: on, off, a group by hand ─────────────────────────────
create function set_class_search(p_ingredient uuid, p_class uuid, p_enabled boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change what is searched for an ingredient.' using errcode = '42501';
  end if;
  update ingredient_class set enabled = coalesce(p_enabled, true)
   where ingredient_id = p_ingredient and class_id = p_class;
  if not found then
    raise exception 'That class is not linked to this ingredient.' using errcode = 'P0002';
  end if;
end $$;

-- A group named by hand: an existing class with that name (any case) is reused, else a hand-made class is
-- created with no words yet (add_class_term fills it). An ATC code is refused: the groups from the ATC code are
-- the daily run's, and a code is never a search word. A link that already exists keeps what it is and is
-- switched on; a class from the ATC code is never turned into a manual one.
create function add_search_group(p_ingredient uuid, p_name_en text) returns uuid
language plpgsql security definer set search_path = public as $$
declare
  v_name  text := regexp_replace(btrim(coalesce(p_name_en, '')), '\s+', ' ', 'g');
  v_code  text;
  v_id    uuid;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change what is searched for an ingredient.' using errcode = '42501';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
  if char_length(v_name) < 2 or char_length(v_name) > 120 then
    raise exception 'A group name must be 2 to 120 characters long.' using errcode = '22023';
  end if;
  if v_name ~* '^[A-Z](\d{2}([A-Z]{1,2}(\d{2})?)?)?$' then
    raise exception 'That is an ATC code. The groups from the ATC code are added by the daily run; name the group in words.'
      using errcode = '22023';
  end if;
  select id into v_id from drug_class where lower(name_en) = lower(v_name) order by created_at limit 1;
  if v_id is null then
    v_code := btrim(left(upper(regexp_replace(v_name, '[^A-Za-z0-9]+', '_', 'g')), 60), '_');
    if v_code = '' then
      v_code := 'GROUP';
    end if;
    if exists (select 1 from drug_class where code = v_code) then
      v_code := left(v_code, 44) || '_' || to_char(now() at time zone 'UTC', 'YYYYMMDDHH24MISS');
    end if;
    insert into drug_class (code, name_en, origin) values (v_code, v_name, 'hand') returning id into v_id;
  end if;
  insert into ingredient_class (ingredient_id, class_id, relation, enabled)
  values (p_ingredient, v_id, 'manual', true)
  on conflict (ingredient_id, class_id) do update set enabled = true;
  return v_id;
end $$;

-- Only a manual group leaves an ingredient. A class from the ATC code stays: switch its words off instead.
create function unlink_search_group(p_ingredient uuid, p_class uuid) returns void
language plpgsql security definer set search_path = public as $$
declare
  v_relation text;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change what is searched for an ingredient.' using errcode = '42501';
  end if;
  select relation into v_relation from ingredient_class
   where ingredient_id = p_ingredient and class_id = p_class;
  if v_relation is null then
    raise exception 'That group is not linked to this ingredient.' using errcode = 'P0002';
  end if;
  if v_relation <> 'manual' then
    raise exception 'A class from the ATC code cannot be removed. Switch its words off instead.' using errcode = '22023';
  end if;
  delete from ingredient_class where ingredient_id = p_ingredient and class_id = p_class;
end $$;

revoke all on function set_class_search(uuid, uuid, boolean) from public, anon;
revoke all on function add_search_group(uuid, text) from public, anon;
revoke all on function unlink_search_group(uuid, uuid) from public, anon;
grant execute on function set_class_search(uuid, uuid, boolean) to authenticated;
grant execute on function add_search_group(uuid, text) to authenticated;
grant execute on function unlink_search_group(uuid, uuid) to authenticated;

-- ───────────────────────────── how a document was found ─────────────────────────────
-- 'name' when one of the ingredient's own names matched; else the relation of the class whose word matched,
-- the nearest first ('group', then 'manual', then 'parent'); null when nothing of this ingredient matched.
-- Not for the app: ingredient_screen() reads it.
create function ingredient_match_relation(p_ingredient uuid, p_document uuid) returns text
language sql stable set search_path = public as $$
  select coalesce(
    (select 'name' from match m where m.document_id = p_document and m.ingredient_id = p_ingredient limit 1),
    (select ic.relation
       from match m join ingredient_class ic on ic.class_id = m.class_id and ic.ingredient_id = p_ingredient
      where m.document_id = p_document
      order by case ic.relation when 'group' then 1 when 'manual' then 2 else 3 end
      limit 1))
$$;
revoke all on function ingredient_match_relation(uuid, uuid) from public, anon, authenticated;

-- ───────────────────────────── the Ingredients screen (0039), told apart ─────────────────────────────
-- As 0039, with: each mention's relation and class_name; each class's relation and enabled; class_words,
-- class_languages and the literature searches counted over the classes that are searched. A mention found by
-- a class since switched off stays on the screen (it was found), labelled by its class.
create or replace function ingredient_screen(p_ingredient uuid, p_from date, p_to date) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_classes  uuid[];
  v_enabled  uuid[];
  v_from     timestamptz := p_from::timestamp at time zone 'Africa/Cairo';
  v_to       timestamptz := (p_to + 1)::timestamp at time zone 'Africa/Cairo';
begin
  perform ingredient_screen_check(p_ingredient, p_from, p_to);
  select coalesce(array_agg(ic.class_id), '{}'),
         coalesce(array_agg(ic.class_id) filter (where ic.enabled), '{}')
    into v_classes, v_enabled
    from ingredient_class ic where ic.ingredient_id = p_ingredient;

  return (
    with docs as (
      -- every notice and paper dated in the days with a match for the ingredient or one of its classes
      select d.id, d.source_id, d.title_orig, d.lang, d.doc_type, d.published_date, d.first_seen_at,
             d.structured, d.is_backfill, s.kind, s.regulator_id, r.name as regulator_name,
             r.country_name, r.country_code,
             document_link(d, s, r) as link,
             coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date) as day,
             coalesce((select bool_or(m.ingredient_id = p_ingredient)
                         from match m
                        where m.document_id = d.id
                          and (m.ingredient_id = p_ingredient or m.class_id = any (v_classes))), false) as by_name
        from document d
        join source s on s.id = d.source_id
        join regulator r on r.id = s.regulator_id
       where d.id in (select m.document_id from match m
                       where m.ingredient_id = p_ingredient or m.class_id = any (v_classes))
         and coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date)
             between p_from and p_to
    ),
    mentions as (
      select dd.regulator_id, dd.kind, dd.day, dd.first_seen_at, dd.id,
             jsonb_build_object(
               'document_id', dd.id,
               'source_id', dd.source_id,
               'regulator_id', dd.regulator_id,
               'regulator_name', dd.regulator_name,
               'country_name', dd.country_name,
               'country_code', dd.country_code,
               'title', dd.title_orig,
               'lang', dd.lang,
               'link', dd.link,
               'email_id', case when dd.structured ->> 'inbound_email_id' ~* '^[0-9a-f-]{36}$'
                                then dd.structured ->> 'inbound_email_id' end,
               'email_r2_key', dd.structured ->> 'raw_r2_key',
               'date', dd.day,
               'published_date', dd.published_date,
               'first_seen_at', dd.first_seen_at,
               'doc_type', dd.doc_type,
               'terms', (select coalesce(jsonb_agg(jsonb_build_object('text', w.word, 'lang', w.wlang)
                                                   order by lower(w.word), w.wlang), '[]'::jsonb)
                           from (select distinct on (lower(btrim(m.matched_text)), coalesce(it.lang, ct.lang))
                                        btrim(m.matched_text) as word, coalesce(it.lang, ct.lang) as wlang
                                   from match m
                                   left join ingredient_term it on it.id = m.term_id
                                   left join class_term ct on ct.id = m.class_term_id
                                  where m.document_id = dd.id
                                    and (m.ingredient_id = p_ingredient or m.class_id = any (v_classes))
                                  order by lower(btrim(m.matched_text)), coalesce(it.lang, ct.lang), m.field, m.created_at,
                                           m.id) w),
               'by_class', not dd.by_name,
               'relation', coalesce(ingredient_match_relation(p_ingredient, dd.id), 'name'),
               'class_name', case when dd.by_name then null else
                               (select c.name_en
                                  from match m
                                  join ingredient_class ic on ic.class_id = m.class_id and ic.ingredient_id = p_ingredient
                                  join drug_class c on c.id = m.class_id
                                 where m.document_id = dd.id
                                 order by case ic.relation when 'group' then 1 when 'manual' then 2 else 3 end, c.name_en
                                 limit 1) end,
               'is_backfill', dd.is_backfill or coalesce(iss.is_backfill, false),
               'sections', case when dd.kind = 'spc' then dd.structured -> 'sections' end,
               'issue_id', iss.id,
               'issue_status', iss.status,
               'decision', dec.j
             ) as j
        from docs dd
        left join lateral (
          select i.id, i.status, i.is_backfill
            from issue_document idd
            join issue i on i.id = idd.issue_id
           where idd.document_id = dd.id
             and idd.method <> 'suggested'
           order by coalesce(i.anchor_document_id = dd.id, false) desc, i.created_at
           limit 1
        ) iss on true
        left join lateral (
          select jsonb_build_object('to_status', re.to_status, 'person', p.full_name,
                                    'at', re.created_at, 'comment', re.comment) as j
            from review_event re
            join person p on p.id = re.person_id
           where re.issue_id = iss.id
           order by re.created_at desc, re.id desc
           limit 1
        ) dec on true
       where dd.kind <> 'literature'
    ),
    regs as (
      select r.id, r.name, r.country_name, r.country_code, r.homepage,
             exists (select 1 from regulator_page p where p.regulator_id = r.id) as hers
        from regulator r
       where exists (select 1 from regulator_page p where p.regulator_id = r.id)
          or exists (select 1 from source s where s.regulator_id = r.id and s.kind not in ('spc', 'literature'))
    ),
    reads as (
      select s.regulator_id,
             count(*) as runs,
             count(*) filter (where not source_run_failed(sr.error)) as ok,
             count(*) filter (where source_run_failed(sr.error)) as failed
        from source_run sr
        join source s on s.id = sr.source_id
       where s.kind not in ('spc', 'literature')
         and sr.started_at >= v_from
         and sr.started_at < v_to
       group by s.regulator_id
    ),
    papers as (
      select dd.id, dd.structured, dd.by_name from docs dd where dd.kind = 'literature'
    ),
    searches as (
      select lower(regexp_replace(btrim(i.inn_en), '\s+', ' ', 'g')) as query
        from ingredient i where i.id = p_ingredient
      union
      select lower(regexp_replace(btrim(ct.term), '\s+', ' ', 'g'))
        from class_term ct where ct.class_id = any (v_enabled) and ct.lang = 'en'
    ),
    by_query as (
      select lower(regexp_replace(btrim(q ->> 'query'), '\s+', ' ', 'g')) as query,
             min(q ->> 'kind') as kind,
             count(*) filter (where q -> 'db' ? 'pubmed') as pubmed,
             count(*) filter (where q -> 'db' ? 'pmc') as pmc
        from papers pp
       cross join lateral jsonb_array_elements(
               case when jsonb_typeof(pp.structured -> 'queries') = 'array' then pp.structured -> 'queries'
                    else '[]'::jsonb end) q
       where jsonb_typeof(q) = 'object'
       group by 1
    )
    select jsonb_build_object(
      'ingredient', (
        select jsonb_build_object(
                 'id', i.id,
                 'inn_en', i.inn_en,
                 'atc_code', i.atc_code,
                 'active', i.active,
                 'classes', coalesce((select jsonb_agg(jsonb_build_object('id', c.id, 'code', c.code,
                                                                          'name_en', c.name_en, 'origin', c.origin,
                                                                          'relation', ic.relation,
                                                                          'enabled', ic.enabled)
                                                       order by c.name_en)
                                        from ingredient_class ic join drug_class c on c.id = ic.class_id
                                       where ic.ingredient_id = p_ingredient), '[]'::jsonb),
                 'names', (select count(*) from ingredient_term t where t.ingredient_id = i.id),
                 'name_languages', (select count(distinct t.lang) from ingredient_term t where t.ingredient_id = i.id),
                 'class_words', (select count(*) from class_term ct where ct.class_id = any (v_enabled)),
                 'class_languages', (select count(distinct ct.lang) from class_term ct
                                      where ct.class_id = any (v_enabled)))
          from ingredient i where i.id = p_ingredient),
      'from', p_from,
      'to', p_to,
      'regulators', coalesce((
        select jsonb_agg(jsonb_build_object(
                 'id', g.id,
                 'name', g.name,
                 'country_name', g.country_name,
                 'country_code', g.country_code,
                 'homepage', g.homepage,
                 'hers', g.hers,
                 'runs', coalesce(rd.runs, 0),
                 'ok', coalesce(rd.ok, 0),
                 'failed', coalesce(rd.failed, 0),
                 'unread_page', exists (
                   select 1 from regulator_page p
                    where p.regulator_id = g.id
                      and p.kind in ('safety', 'dhpc')
                      and not exists (select 1 from source s where s.id = any (p.read_by) and s.enabled)),
                 'pages', coalesce((select jsonb_agg(jsonb_build_object(
                                             'id', p.id, 'regulator_id', p.regulator_id, 'kind', p.kind,
                                             'sort', p.sort, 'label', p.label, 'url', p.url,
                                             'read_by', to_jsonb(p.read_by), 'partial', p.partial,
                                             'note', p.note)
                                           order by p.sort, p.label)
                                      from regulator_page p where p.regulator_id = g.id), '[]'::jsonb),
                 'sources', coalesce((select jsonb_agg(jsonb_build_object(
                                               'id', s.id, 'regulator_id', s.regulator_id, 'kind', s.kind,
                                               'channel', s.channel, 'url', s.url, 'page_url', s.page_url,
                                               'enabled', s.enabled, 'health', s.health, 'notes', s.notes)
                                             order by s.id)
                                        from source s where s.regulator_id = g.id), '[]'::jsonb),
                 'mentions', coalesce((select jsonb_agg(mm.j order by mm.day desc, mm.first_seen_at desc, mm.id)
                                         from mentions mm
                                        where mm.regulator_id = g.id and mm.kind <> 'spc'), '[]'::jsonb))
               order by not g.hers, g.country_name, g.name)
          from regs g
          left join reads rd on rd.regulator_id = g.id), '[]'::jsonb),
      'label_changes', coalesce((select jsonb_agg(mm.j order by mm.day desc, mm.first_seen_at desc, mm.id)
                                   from mentions mm where mm.kind = 'spc'), '[]'::jsonb),
      'literature', jsonb_build_object(
        'papers', (select count(*) from papers),
        'by_name', (select count(*) from papers pp where pp.by_name),
        'by_class', (select count(*) from papers pp where not pp.by_name),
        'pubmed', (select count(*) from papers pp where pp.structured -> 'found_in' ? 'pubmed'),
        'pmc', (select count(*) from papers pp where pp.structured -> 'found_in' ? 'pmc'),
        'by_query', coalesce((select jsonb_agg(jsonb_build_object('query', bq.query, 'kind', bq.kind,
                                                                  'pubmed', bq.pubmed, 'pmc', bq.pmc)
                                               order by bq.kind desc, bq.query)
                                from by_query bq
                               where bq.query in (select se.query from searches se)), '[]'::jsonb),
        'first', coalesce((select jsonb_agg(to_jsonb(ip) - 'n' order by ip.n)
                             from ingredient_papers(p_ingredient, p_from, p_to)
                                  with ordinality as ip(document_id, title, lang, journal, day, pubmed_url, pmc_url,
                                                        by_class, is_backfill, first_seen_at, n)
                            where ip.n <= 50), '[]'::jsonb))
    )
  );
end $$;
