-- PHAROS — the Ingredients screen: one ingredient across every source (2026-11-06, Dr Sama's review).
--
-- Dr Sama screens in two passes. The horizontal pass is the Sources screen (0032): per authority, everything
-- it published. This is the vertical pass: one active ingredient, every source, one question: did anyone,
-- anywhere, mention it in the days she chose, and where. The screen (/ingredients/:id) asks
-- ingredient_screen() once for everything it shows, and ingredient_papers() when she wants more papers.
--
-- 1. document_link(d, s, r): the page a person opens for a document, taken out of new_items() so that the two
--    screens agree. Never a feed or an API address (the source's page, else the authority's home page); FDA's
--    Enforcement Report for an openFDA recall; nothing for an e-mail with no web page (email_id and
--    email_r2_key open it); and the source's page for a document stored without an address (a label-watch
--    product with no page of its own). new_items() keeps its signature, its grants and its rows.
-- 2. ingredient_screen(p_ingredient, p_from, p_to): Cairo calendar days, both included, at most 366.
--    - Every authority with a safety or recall source or one of her pages, hers first. Per authority: its
--      reads in those days (source_run of its safety and recall sources; a failure is what
--      source_run_failed() of 0018 says, so a note is not a failure; never filtered by run.trigger, which
--      says 'backfill' for every run before 6 Nov 2026), whether one of her safety or DHPC pages is read by
--      no switched-on source, her pages and its sources.
--    - Its mentions: notices of its sources dated in those days (published, else first seen, in Cairo) with a
--      match for the ingredient or for one of its drug classes. Label-watch notices come apart as label
--      changes; papers come apart as literature. Each mention carries its link, the words that matched and
--      their language, by_class (only class words matched), is_backfill (history: the notice, or the notice
--      it was filed under, was found by a backfill or by the check of the past), its notice (issue: the one
--      it is linked to, not merely suggested for, its anchor first), the notice's status and its latest
--      decision (who, when, comment).
--    - The papers (NCBI literature, PubMed and PubMed Central): how many in all, by database and by search
--      (the ingredient's English name and the English words of its classes, as the daily watch searches
--      them), and the first 50.
-- 3. ingredient_papers(p_ingredient, p_from, p_to): the papers of those days, those naming the ingredient
--    first, newest first, each with its PubMed and PMC links. The screen pages through it 50 at a time.
-- Both read for a member of the team only (security definer with my_role(); 42501 for anyone else).

-- ───────────────────────────── the page a person opens for a document ─────────────────────────────
create function document_link(d document, s source, r regulator) returns text
language sql immutable set search_path = public as $$
  select case
           when d.url like 'email:%' then null
           when d.url ~* '^https?://api\.fda\.gov/' then
             'https://www.accessdata.fda.gov/scripts/ires/index.cfm'
               || coalesce('?Event=' || nullif(btrim(d.structured ->> 'event_id'), ''), '')
           when d.url ~* '(\.(xml|json|rss|atom)([?#]|$)|/(rss|feed|atom)(/|[?#]|$)|^https?://api\.)' then
             coalesce(s.page_url, r.homepage)
           when btrim(coalesce(d.url, '')) = '' then
             coalesce(s.page_url, r.homepage)
           else d.url
         end
$$;
revoke all on function document_link(document, source, regulator) from public, anon;
grant execute on function document_link(document, source, regulator) to authenticated;

-- As in 0032, with the link from document_link(). create or replace keeps the owner, grants and revokes.
create or replace function new_items(p_from timestamptz, p_to timestamptz default now())
returns table (
  document_id     uuid,
  source_id       text,
  regulator_id    text,
  regulator_name  text,
  country_name    text,
  country_code    text,
  source_kind     source_kind,
  title_orig      text,
  lang            text,
  link            text,
  published_date  date,
  first_seen_at   timestamptz,
  doc_type        doc_type,
  matched         boolean,
  r2_key          text,
  mime            text,
  email_id        uuid,
  email_r2_key    text
)
language sql stable security invoker set search_path = public as $$
  select d.id, d.source_id, r.id, r.name, r.country_name, r.country_code, s.kind, d.title_orig, d.lang,
         document_link(d, s, r),
         d.published_date, d.first_seen_at, d.doc_type,
         exists (select 1 from match m where m.document_id = d.id),
         d.r2_key, d.mime,
         case when d.structured ->> 'inbound_email_id' ~* '^[0-9a-f-]{36}$'
              then (d.structured ->> 'inbound_email_id')::uuid end,
         d.structured ->> 'raw_r2_key'
    from document d
    join source s on s.id = d.source_id
    join regulator r on r.id = s.regulator_id
   where d.first_seen_at >= p_from
     and d.first_seen_at < coalesce(p_to, now())
     and not d.is_backfill
     and s.kind not in ('spc', 'literature')
$$;

-- The screen starts from the matches of one ingredient and its classes, then finds each notice's issue and
-- the issue's latest decision.
create index if not exists match_ingredient_id_idx on match (ingredient_id);
create index if not exists match_class_id_idx on match (class_id);
create index if not exists issue_document_document_id_idx on issue_document (document_id);
create index if not exists review_event_issue_created_idx on review_event (issue_id, created_at desc);

-- ───────────────────────────── who may ask, and for which days ─────────────────────────────
create function ingredient_screen_check(p_ingredient uuid, p_from date, p_to date) returns void
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can screen an ingredient.' using errcode = '42501';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose days whose end is on or after their start.' using errcode = '22023';
  end if;
  if p_to - p_from > 365 then
    raise exception 'Choose at most 366 days.' using errcode = '22023';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
end $$;
revoke all on function ingredient_screen_check(uuid, date, date) from public, anon, authenticated;

-- ───────────────────────────── the papers ─────────────────────────────
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
  first_seen_at  timestamptz
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
           d.first_seen_at
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

-- ───────────────────────────── one ingredient across every source ─────────────────────────────
create function ingredient_screen(p_ingredient uuid, p_from date, p_to date) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_classes  uuid[];
  v_from     timestamptz := p_from::timestamp at time zone 'Africa/Cairo';
  v_to       timestamptz := (p_to + 1)::timestamp at time zone 'Africa/Cairo';
begin
  perform ingredient_screen_check(p_ingredient, p_from, p_to);
  select coalesce(array_agg(ic.class_id), '{}') into v_classes
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
        from class_term ct where ct.class_id = any (v_classes) and ct.lang = 'en'
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
                                                                          'name_en', c.name_en, 'origin', c.origin)
                                                       order by c.name_en)
                                        from drug_class c where c.id = any (v_classes)), '[]'::jsonb),
                 'names', (select count(*) from ingredient_term t where t.ingredient_id = i.id),
                 'name_languages', (select count(distinct t.lang) from ingredient_term t where t.ingredient_id = i.id),
                 'class_words', (select count(*) from class_term ct where ct.class_id = any (v_classes)),
                 'class_languages', (select count(distinct ct.lang) from class_term ct
                                      where ct.class_id = any (v_classes)))
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
revoke all on function ingredient_screen(uuid, date, date) from public, anon;
grant execute on function ingredient_screen(uuid, date, date) to authenticated;
