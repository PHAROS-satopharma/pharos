-- PHAROS — a class's words in notices but not in the literature (2026-11-06, after the review of lornoxicam's
-- NSAID class: its English words find about 10,000 PubMed and 43,000 PubMed Central papers a year, against 15 and
-- 182 for lornoxicam itself).
--
-- ingredient_class.literature: whether the class's ENGLISH words are also searched on PubMed and PubMed Central
-- for this ingredient (the daily NCBI watch, Store.class_words; the live count, literature-search; the weekly
-- report; the screen's literature searches; the readiness NCBI count). It only counts while the class is searched at all (enabled): a
-- class switched off is looked for nowhere. Notices are matched as before, in every language.
--
-- Every existing link stays in the literature (default true): nothing changes on deploy. Papers already found
-- by a class word are kept; they stay on the screen as found. A word switched back on after months is looked
-- back on again (collectors/parsers/pubmed.py, STALE_DAYS); after a shorter pause its days are caught up.

alter table ingredient_class add column literature boolean not null default true;

comment on column ingredient_class.literature is
  'Whether the class''s English words are also searched on PubMed and PubMed Central for this ingredient (0051).';

-- The switch is dated like the search switch (trigger ingredient_class_relation of 0049).
create or replace function ingredient_class_relation() returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' and new.relation = 'group'
     and exists (select 1 from drug_class c where c.id = new.class_id and c.origin = 'hand') then
    new.relation := 'manual';
  end if;
  if tg_op = 'UPDATE' and (new.enabled is distinct from old.enabled or new.literature is distinct from old.literature) then
    new.changed_at := now();
  end if;
  return new;
end $$;

-- ───────────────────────────── administrators: in the literature or not ─────────────────────────────
create function set_class_literature(p_ingredient uuid, p_class uuid, p_on boolean) returns void
language plpgsql security definer set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change what is searched for an ingredient.' using errcode = '42501';
  end if;
  update ingredient_class set literature = coalesce(p_on, true)
   where ingredient_id = p_ingredient and class_id = p_class;
  if not found then
    raise exception 'That class is not linked to this ingredient.' using errcode = 'P0002';
  end if;
end $$;

revoke all on function set_class_literature(uuid, uuid, boolean) from public, anon;
grant execute on function set_class_literature(uuid, uuid, boolean) to authenticated;

-- ───────────────────────────── the Ingredients screen, as 0049 ─────────────────────────────
-- As 0049, with: each class's literature switch; the literature searches counted over the classes that are
-- searched AND in the literature. class_words and class_languages still count every searched class (notices).
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

-- ───────────────────────────── how far an ingredient is prepared, as 0045 ─────────────────────────────
-- As 0045, with: NCBI waits only for the English words of the classes that are searched AND in the literature.
-- A class kept to notices is never searched on PubMed or PMC, so nothing is waited for on its words there;
-- its words still count for the class and the check of the past.
create or replace function ingredient_readiness(p_ingredient uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_ing        ingredient%rowtype;
  v_linked     int;         -- classes linked to it, searched or not
  v_classes    uuid[];      -- the linked classes whose words are searched
  v_lit        uuid[];      -- of them, the ones also searched on PubMed and PMC (0051, ingredient_class.literature)
  v_words      text[];      -- the English words NCBI searches: the name and the English class words
  v_names      jsonb;
  v_class      jsonb;
  v_past       jsonb;
  v_ncbi       jsonb;
  v_labels     jsonb;
  v_eurd       jsonb;
  v_telegram   jsonb;
  v_ready      boolean;
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can read how far an ingredient is prepared.' using errcode = '42501';
  end if;
  select * into v_ing from ingredient where id = p_ingredient;
  if not found then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
  -- Every class linked to it (made from the ATC code by the daily run, or given by hand), and of them the ones
  -- whose words are searched: a class switched off in its search profile (0049, ingredient_class.enabled; the
  -- class above its group starts off) is searched nowhere, so nothing is waited for on its words. The column is
  -- 0049's: PL/pgSQL reads it when the function runs, so 0045 can be applied before or after 0049.
  select count(*) into v_linked from ingredient_class ic where ic.ingredient_id = p_ingredient;
  select coalesce(array_agg(ic.class_id), '{}') into v_classes
    from ingredient_class ic where ic.ingredient_id = p_ingredient and ic.enabled;
  select coalesce(array_agg(ic.class_id), '{}') into v_lit
    from ingredient_class ic where ic.ingredient_id = p_ingredient and ic.enabled and ic.literature;

  -- names: a name in how many of the languages the authorities write in (a code is not a name)
  with langs as (
    select distinct unnest(r.languages) as lang from regulator r
  ), named as (
    select distinct t.lang from ingredient_term t where t.ingredient_id = p_ingredient and t.kind <> 'code'
  )
  select jsonb_build_object(
           'languages_with_a_name', (select count(*) from named),
           'of',                    (select count(*) from langs),
           'missing', coalesce((select jsonb_agg(l.lang order by l.lang) from langs l
                                 where l.lang not in (select lang from named)), '[]'::jsonb))
    into v_names;

  -- class: the classes linked to it (made from the ATC code or added by hand), and the words of those searched
  select jsonb_build_object(
           'atc',       v_ing.atc_code is not null,
           'classes',   v_linked,
           'words',     (select count(*) from class_term ct where ct.class_id = any (v_classes)),
           'confirmed', coalesce((select bool_and(dc.confirmed_at is not null) from drug_class dc
                                   where dc.id = any (v_classes)), false))
    into v_class;

  -- the check of the past: a word is due while rematched_at is null or older than its last change (0034)
  with due as (
    select count(*) as n
      from (select t.rematched_at, t.changed_at from ingredient_term t
             where t.ingredient_id = p_ingredient and t.kind <> 'code'
            union all
            select ct.rematched_at, ct.changed_at from class_term ct where ct.class_id = any (v_classes)) w
     where w.rematched_at is null or w.rematched_at < w.changed_at
  )
  select jsonb_build_object(
           'done',        (select n from due) = 0,
           'words_due',   (select n from due),
           'job_running', exists (select 1 from rematch_job j where j.finished_at is null))
    into v_past;

  -- NCBI: PubMed and PubMed Central, each searched for the name and every English class word (0035)
  select coalesce(array_agg(distinct w), '{}') into v_words
    from (select lower(btrim(regexp_replace(v_ing.inn_en, '\s+', ' ', 'g'))) as w
          union all
          select lower(btrim(regexp_replace(ct.term, '\s+', ' ', 'g')))
            from class_term ct where ct.class_id = any (v_lit) and ct.lang = 'en') x
   where w <> '';
  with runs as (
    select ls.look_back_done_at, ls.last_searched_at
      from literature_search ls
     where ls.query = any (v_words) and ls.db in ('pubmed', 'pmc')
  )
  select jsonb_build_object(
           'searches',       (select count(*) from runs),
           'expected',       2 * cardinality(v_words),
           'look_back_done', cardinality(v_words) > 0
                             and (select count(*) from runs) = 2 * cardinality(v_words)
                             and coalesce((select bool_and(look_back_done_at is not null) from runs), false),
           'last_run',       (select max(last_searched_at) from runs))
    into v_ncbi;

  -- the label watch: every switched-on labels source; read when it ran since the ingredient was added and did
  -- not fail (a note is not a failure: source_run_failed, 0018); its products are the active ones it found
  with src as (
    select s.id, r.country_name, r.name as regulator_name,
           (select count(*) from spc_product sp
             where sp.ingredient_id = p_ingredient and sp.source_id = s.id and sp.active) as products,
           exists (select 1 from source_run sr
                    where sr.source_id = s.id and sr.started_at >= v_ing.created_at
                      and not source_run_failed(sr.error)) as is_read
      from source s join regulator r on r.id = s.regulator_id
     where s.kind = 'spc' and s.enabled
  ), country as (
    select country_name, sum(products) as products, bool_and(is_read) as is_read from src group by country_name
  )
  select jsonb_build_object(
           'products',  coalesce((select sum(products) from src), 0),
           'by_source', coalesce((select jsonb_object_agg(id, jsonb_build_object(
                                     'country', country_name, 'regulator', regulator_name,
                                     'products', products, 'read', is_read)) from src), '{}'::jsonb),
           'waiting',   coalesce((select jsonb_agg(country_name order by country_name) from country
                                   where not is_read), '[]'::jsonb),
           'empty',     coalesce((select jsonb_agg(country_name order by country_name) from country
                                   where is_read and products = 0), '[]'::jsonb),
           'first_snapshot', exists (select 1 from spc_snapshot ss join spc_product sp on sp.id = ss.spc_product_id
                                      where sp.ingredient_id = p_ingredient and sp.active),
           'japan_code', exists (select 1 from ingredient_term t
                                  where t.ingredient_id = p_ingredient and t.kind = 'code' and t.country_code = 'JP'))
    into v_labels;

  -- EMA's EURD list: the row for the substance alone before a combination (0028)
  select jsonb_build_object(
           'found',           e.eurd_id is not null,
           'list_read',       exists (select 1 from eurd_entry),
           'frequency',       e.frequency,
           'dlp',             e.dlp,
           'next_submission', coalesce(e.next_submission_date, e.submission_date))
    into v_eurd
    from (select null) z
    left join lateral (select * from eurd_entry x where x.ingredient_id = p_ingredient
                        order by x.combination, x.eurd_id limit 1) e on true;

  -- who hears of it on Telegram: active people with Telegram linked, subscribed to every ingredient or to this one
  select jsonb_build_object('people', coalesce((
           select jsonb_agg(distinct p.full_name order by p.full_name)
             from person p join subscription s on s.person_id = p.id
            where p.active and p.telegram_chat_id is not null and s.kind = 'ingredient'
              and (s.ingredient_id is null or s.ingredient_id = p_ingredient)), '[]'::jsonb))
    into v_telegram;

  v_ready := (v_names ->> 'languages_with_a_name')::int >= 1
         and (not (v_class ->> 'atc')::boolean or v_linked > 0)
         and (v_past ->> 'done')::boolean
         and (v_ncbi ->> 'look_back_done')::boolean
         and ((v_labels ->> 'products')::int > 0 or v_labels -> 'waiting' = '[]'::jsonb)
         and jsonb_array_length(v_telegram -> 'people') >= 1;

  return jsonb_build_object(
    'names', v_names, 'class', v_class, 'past_check', v_past, 'ncbi', v_ncbi, 'label_watch', v_labels,
    'eurd', v_eurd, 'ema_mlm', jsonb_build_object('monitored', exists (select 1 from mlm_entry m
                                                                        where m.ingredient_id = p_ingredient)),
    'telegram', v_telegram, 'ready', v_ready);
end $$;
revoke all on function ingredient_readiness(uuid) from public, anon;
grant execute on function ingredient_readiness(uuid) to authenticated;
