-- PHAROS — any ingredient she adds is covered (2026-11-06, the QPPV's fifth need after her review).
--
-- When Dr Sama saves an ingredient, everything that follows runs by itself over the next days: its drug class
-- and class words from the ATC code (daily, 02:31), the check of the past over the last 12 months of stored
-- notices (daily), NCBI's 12-month look-back for each new search word (daily), the label watch of every
-- country with a labels source (Monday 03:23), and her Telegram messages. Until now nothing told her how far
-- that had got; this migration gives the Ingredients page and the weekly report one answer to read.
--
-- 1. ingredient_readiness(p_ingredient) returns jsonb: what has run and what is still to come, in facts the
--    screen and the report turn into her words. Ready when the ingredient has a name in at least one
--    language, class words (or no ATC code, so no class to wait for), its check of the past is done, NCBI's
--    look-back has finished for every expected search, every watched country's label watch has read since
--    the ingredient was added (a watch that read and found no label is an answer), and at least one person
--    with Telegram linked is subscribed to it (to every ingredient, or to this one). The Japan code, the
--    EURD row and EMA's literature monitoring are facts under the line and never hold Ready back.
--    Who may ask: screen_reader() as 0040 — a member of the team, or the report's direct connection
--    (42501 for anyone else, P0002 for an ingredient not on the watchlist). Signed-out visitors cannot call it.
--      {names:      {languages_with_a_name, of, missing: [lang]},        -- codes are not names
--       class:      {atc, classes, words, confirmed},
--       past_check: {done, words_due, job_running},
--       ncbi:       {searches, expected, look_back_done, last_run},      -- expected: 2 per English word
--       label_watch:{products, by_source: {<source>: {country, regulator, products, read}},
--                    waiting: [country], empty: [country], first_snapshot, japan_code},
--       eurd:       {found, list_read, frequency, dlp, next_submission},
--       ema_mlm:    {monitored},
--       telegram:   {people: [name]},
--       ready}
-- 2. Her subscription to every ingredient (kind 'ingredient', no ingredient), guarded by her address as 0033:
--    on any other database this inserts nothing, and it never adds a second one.

-- ───────────────────────────── how far an ingredient is prepared ─────────────────────────────
create or replace function ingredient_readiness(p_ingredient uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_ing        ingredient%rowtype;
  v_classes    uuid[];
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
  select coalesce(array_agg(ic.class_id), '{}') into v_classes
    from ingredient_class ic where ic.ingredient_id = p_ingredient;

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

  -- class: the classes made from the ATC code (or added by hand) and their words
  select jsonb_build_object(
           'atc',       v_ing.atc_code is not null,
           'classes',   cardinality(v_classes),
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
            from class_term ct where ct.class_id = any (v_classes) and ct.lang = 'en') x
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
                      and not source_run_failed(sr.error)) as read
      from source s join regulator r on r.id = s.regulator_id
     where s.kind = 'spc' and s.enabled
  ), country as (
    select country_name, sum(products) as products, bool_and(read) as read from src group by country_name
  )
  select jsonb_build_object(
           'products',  coalesce((select sum(products) from src), 0),
           'by_source', coalesce((select jsonb_object_agg(id, jsonb_build_object(
                                     'country', country_name, 'regulator', regulator_name,
                                     'products', products, 'read', read)) from src), '{}'::jsonb),
           'waiting',   coalesce((select jsonb_agg(country_name order by country_name) from country
                                   where not read), '[]'::jsonb),
           'empty',     coalesce((select jsonb_agg(country_name order by country_name) from country
                                   where read and products = 0), '[]'::jsonb),
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
         and (not (v_class ->> 'atc')::boolean or (v_class ->> 'words')::int > 0)
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

-- ───────────────────────────── her subscription to every ingredient ─────────────────────────────
-- As 0033: by her address, never twice; on any other database this inserts nothing.
insert into subscription (person_id, kind, ingredient_id)
select p.id, 'ingredient', null
  from person p
 where lower(p.email) = 'sama.mosaad@satopharma.com'
   and not exists (select 1 from subscription s
                    where s.person_id = p.id and s.kind = 'ingredient' and s.ingredient_id is null);
