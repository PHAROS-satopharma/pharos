-- PHAROS — Europe PMC, the second literature source (2026-11-06).
--
-- The Europe PMC watch (collectors/parsers/europepmc.py, source 'europepmc', synced from collectors/sources.yaml)
-- searches Europe PMC every day for the words PubMed is searched for, adding what PubMed misses: preprints
-- (medRxiv, bioRxiv, Research Square …) and papers that name a word only inside their open full text. One paper is
-- one document whichever source found it first (collectors/parsers/_literature.py): a paper NCBI stored is only
-- marked as found by Europe PMC too ('europepmc' in document.structured.found_in and in the databases of its search
-- words in structured.queries), and the other way round. A preprint carries structured.preprint = true and
-- structured.europepmc_url, its Europe PMC page (a preprint has no PubMed or PMC link).
--
-- 1. literature_search (0035) remembers Europe PMC's searches too: db may be 'europepmc'.
-- 2. ingredient_papers() gains two columns at the END (the weekly report and the pack read it by name):
--      europepmc_url  the paper's Europe PMC page (https only), else null
--      preprint       true for a preprint: the screen says "Preprint, not peer reviewed"
--    The function is dropped and made again (its columns change); the grants are as 0039.
-- 3. ingredient_screen(), as 0051, with: the literature counts 'europepmc' (papers Europe PMC found) and
--    'preprints'; each search's 'europepmc' count in 'by_query'; the first 50 papers read with the two new columns.
-- No row changes: papers stored before this migration were found by NCBI alone, as their found_in already says.

-- ───────────────────────────── 1. Europe PMC's searches ─────────────────────────────
alter table literature_search drop constraint literature_search_db_check;
alter table literature_search add constraint literature_search_db_check check (db in ('pubmed', 'pmc', 'europepmc'));
comment on table literature_search is
  'Literature searches run by the collector (NCBI PubMed and PMC, Europe PMC): the 12-month look-back of each new search word, and whether it finished.';

-- ───────────────────────────── 2. the papers, with Europe PMC's page and the preprint flag ─────────────────────────────
drop function ingredient_papers(uuid, date, date);
create function ingredient_papers(p_ingredient uuid, p_from date, p_to date)
returns table (
  document_id    uuid,
  title          text,
  lang           text,
  journal        text,
  day            date,
  pubmed_url     text,
  pmc_url        text,
  by_class       boolean,
  is_backfill    boolean,
  first_seen_at  timestamptz,
  europepmc_url  text,
  preprint       boolean
)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
declare
  v_classes uuid[];
begin
  perform ingredient_screen_check(p_ingredient, p_from, p_to);
  select coalesce(array_agg(ic.class_id), '{}') into v_classes
    from ingredient_class ic where ic.ingredient_id = p_ingredient;
  return query
    select d.id,
           d.title_orig,
           d.lang,
           nullif(btrim(d.structured ->> 'journal'), ''),
           coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date),
           case when d.structured ->> 'pubmed_url' ~ '^https://' then d.structured ->> 'pubmed_url' end,
           case when d.structured ->> 'pmc_url' ~ '^https://' then d.structured ->> 'pmc_url' end,
           not h.by_name,
           d.is_backfill or coalesce(d.structured ->> 'look_back', '') = 'true',
           d.first_seen_at,
           case when d.structured ->> 'europepmc_url' ~ '^https://' then d.structured ->> 'europepmc_url' end,
           coalesce(d.structured ->> 'preprint', '') = 'true'
      from (select m.document_id as doc_id, coalesce(bool_or(m.ingredient_id = p_ingredient), false) as by_name
              from match m
             where m.ingredient_id = p_ingredient or m.class_id = any (v_classes)
             group by m.document_id) h
      join document d on d.id = h.doc_id
      join source s on s.id = d.source_id
     where s.kind = 'literature'
       and coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date) between p_from and p_to
     order by not h.by_name,
              coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date) desc,
              d.first_seen_at desc,
              d.id;
end $$;
revoke all on function ingredient_papers(uuid, date, date) from public, anon;
grant execute on function ingredient_papers(uuid, date, date) to authenticated;

-- ───────────────────────────── 3. the Ingredients screen, as 0051 ─────────────────────────────
-- As 0051, with: 'europepmc' and 'preprints' in the literature counts, 'europepmc' in each search's counts, and the
-- first 50 papers with their Europe PMC page and preprint flag.
create or replace function ingredient_screen(p_ingredient uuid, p_from date, p_to date) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_classes  uuid[];
  v_enabled  uuid[];
  v_lit      uuid[];
  v_from     timestamptz := p_from::timestamp at time zone 'Africa/Cairo';
  v_to       timestamptz := (p_to + 1)::timestamp at time zone 'Africa/Cairo';
begin
  perform ingredient_screen_check(p_ingredient, p_from, p_to);
  select coalesce(array_agg(ic.class_id), '{}'),
         coalesce(array_agg(ic.class_id) filter (where ic.enabled), '{}'),
         coalesce(array_agg(ic.class_id) filter (where ic.enabled and ic.literature), '{}')
    into v_classes, v_enabled, v_lit
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
        from class_term ct where ct.class_id = any (v_lit) and ct.lang = 'en'
    ),
    by_query as (
      select lower(regexp_replace(btrim(q ->> 'query'), '\s+', ' ', 'g')) as query,
             min(q ->> 'kind') as kind,
             count(*) filter (where q -> 'db' ? 'pubmed') as pubmed,
             count(*) filter (where q -> 'db' ? 'pmc') as pmc,
             count(*) filter (where q -> 'db' ? 'europepmc') as europepmc
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
                                                                          'enabled', ic.enabled,
                                                                          'literature', ic.literature)
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
        'europepmc', (select count(*) from papers pp where pp.structured -> 'found_in' ? 'europepmc'),
        'preprints', (select count(*) from papers pp where coalesce(pp.structured ->> 'preprint', '') = 'true'),
        'by_query', coalesce((select jsonb_agg(jsonb_build_object('query', bq.query, 'kind', bq.kind,
                                                                  'pubmed', bq.pubmed, 'pmc', bq.pmc,
                                                                  'europepmc', bq.europepmc)
                                               order by bq.kind desc, bq.query)
                                from by_query bq
                               where bq.query in (select se.query from searches se)), '[]'::jsonb),
        'first', coalesce((select jsonb_agg(to_jsonb(ip) - 'n' order by ip.n)
                             from ingredient_papers(p_ingredient, p_from, p_to)
                                  with ordinality as ip(document_id, title, lang, journal, day, pubmed_url, pmc_url,
                                                        by_class, is_backfill, first_seen_at, europepmc_url,
                                                        preprint, n)
                            where ip.n <= 50), '[]'::jsonb))
    )
  );
end $$;
