-- PHAROS — readiness counts the label watch per database page (2026-11-07).
-- ingredient_readiness(), as 0092, with one more field under label_watch:
--   pages  her database pages (regulator_page, kind 'database'), for this ingredient:
--            total          every database page of her list
--            read           a switched-on labels source reading the page has run since the ingredient was added
--                           and did not fail
--            waiting        a source reads it, but has not run for this ingredient yet (the next weekly run)
--            not_read       no labels source reads it; its note on the Sources page says why
--            waiting_pages  "Country: page" of the waiting ones
-- Until now readiness counted sources and countries, while her list is of pages: Medsafe's two lists, CBG's
-- English and Dutch pages, and the eight pages the app cannot read were invisible in it. What holds Ready is
-- unchanged. Everything else is exactly 0092's.

create or replace function ingredient_readiness(p_ingredient uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_ing        ingredient%rowtype;
  v_linked     int;         -- classes linked to it, searched or not
  v_classes    uuid[];      -- the linked classes whose words are searched
  v_lit        uuid[];      -- of them, the ones also searched on PubMed and PMC (0051, ingredient_class.literature)
  v_words      text[];      -- the English words searched: the name and the English class words
  v_name       text;        -- the name, as its PubMed search is stored
  v_names      jsonb;
  v_class      jsonb;
  v_past       jsonb;
  v_ncbi       jsonb;
  v_epmc       jsonb;
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

  -- the English words searched: the name and the English class words (0035); Europe PMC's count is over all of them
  select coalesce(array_agg(distinct w), '{}') into v_words
    from (select lower(btrim(regexp_replace(v_ing.inn_en, '\s+', ' ', 'g'))) as w
          union all
          select lower(btrim(regexp_replace(ct.term, '\s+', ' ', 'g')))
            from class_term ct where ct.class_id = any (v_lit) and ct.lang = 'en') x
   where w <> '';
  -- NCBI: what holds Ready is the name's own PubMed search (titles and abstracts) and its look-back
  v_name := lower(btrim(regexp_replace(coalesce(v_ing.inn_en, ''), '\s+', ' ', 'g')));
  with runs as (
    select ls.look_back_done_at, ls.last_searched_at
      from literature_search ls
     where ls.db = 'pubmed' and ls.query = v_name and v_name <> ''
  )
  select jsonb_build_object(
           'searches',       (select count(*) from runs),
           'expected',       case when v_name <> '' then 1 else 0 end,
           'look_back_done', v_name <> ''
                             and coalesce((select bool_and(look_back_done_at is not null) from runs), false),
           'last_run',       (select max(last_searched_at) from runs))
    into v_ncbi;

  -- Europe PMC (0066): the same words, once each; its look-back fills in the background and holds nothing (0092)
  with runs as (
    select ls.look_back_done_at, ls.last_searched_at
      from literature_search ls
     where ls.query = any (v_words) and ls.db = 'europepmc'
  )
  select jsonb_build_object(
           'watched',        exists (select 1 from source s where s.id = 'europepmc' and s.enabled),
           'holds_ready',    false,
           'searches',       (select count(*) from runs),
           'expected',       cardinality(v_words),
           'look_back_done', cardinality(v_words) > 0
                             and (select count(*) from runs) = cardinality(v_words)
                             and coalesce((select bool_and(look_back_done_at is not null) from runs), false),
           'last_run',       (select max(last_searched_at) from runs))
    into v_epmc;

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
  ), pg as (
    -- her database pages (regulator_page, kind database): read when a switched-on labels source reading the page
    -- has run since the ingredient was added; waiting when it has not yet; not read when no source reads it
    select coalesce(r.country_name, p.regulator_id) as country, p.label, p.sort,
           exists (select 1 from src where src.id = any(p.read_by)) as has_reader,
           exists (select 1 from src where src.id = any(p.read_by) and src.is_read) as is_read
      from regulator_page p
      left join regulator r on r.id = p.regulator_id
     where p.kind = 'database'
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
                                  where t.ingredient_id = p_ingredient and t.kind = 'code' and t.country_code = 'JP'),
           'pages', jsonb_build_object(
             'total',    (select count(*) from pg),
             'read',     (select count(*) from pg where is_read),
             'waiting',  (select count(*) from pg where has_reader and not is_read),
             'not_read', (select count(*) from pg where not has_reader),
             'waiting_pages', coalesce((select jsonb_agg(country || ': ' || label order by country, sort)
                                          from pg where has_reader and not is_read), '[]'::jsonb)))
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
    'names', v_names, 'class', v_class, 'past_check', v_past, 'ncbi', v_ncbi, 'europepmc', v_epmc,
    'label_watch', v_labels,
    'eurd', v_eurd, 'ema_mlm', jsonb_build_object('monitored', exists (select 1 from mlm_entry m
                                                                        where m.ingredient_id = p_ingredient)),
    'telegram', v_telegram, 'ready', v_ready);
end $$;
revoke all on function ingredient_readiness(uuid) from public, anon;
grant execute on function ingredient_readiness(uuid) to authenticated;
