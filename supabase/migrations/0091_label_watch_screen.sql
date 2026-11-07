-- PHAROS — what the label watch read, per database page, on the Ingredients screen and the Sources page
-- (2026-11-07).
--
-- Her first column is the regulators' database pages (regulator_page, kind 'database'). Until now the screen
-- showed only the label changes detected: not how many products each database lists for the ingredient, which
-- labels could not be read and why, whether a list broke off, or which pages are not read at all and why.
--
-- * spc_product.last_error / last_error_at: the error of the last read of the label that failed, cleared when a
--   read succeeds (collectors/spc/run.py, mark_unread / mark_checked). Such a label is unread, and read first
--   next run.
-- * spc_listing: the newest list of an ingredient's products from each label source, and whether it was read to
--   its end (complete) or what was not (gaps). A list that broke off switches nothing off (run.py); this says
--   so on screen.
-- * label_watch(ingredient): every database page with, for each label source reading it, the ingredient's
--   products, the labels read, the labels unread with their errors, the newest label date, the newest change
--   detected, the list and the source's last run. A page no source reads keeps its reason (note).
-- * label_watch_sources(): the same counts over every ingredient, per label source, for the Sources page.

alter table public.spc_product add column if not exists last_error text;
alter table public.spc_product add column if not exists last_error_at timestamptz;
comment on column public.spc_product.last_error is
  'The error of the last read of this label that failed; null once a read succeeds (0091).';

create table if not exists public.spc_listing (
  source_id      text not null references source(id),
  ingredient_id  uuid not null references ingredient(id) on delete cascade,
  listed_at      timestamptz not null default now(),
  products       int not null,                    -- active products after this list (those it did not reach kept)
  complete       boolean not null,                -- the list was read to its end
  gaps           text,                            -- what was not read, when not complete
  primary key (source_id, ingredient_id)
);
comment on table public.spc_listing is
  'The newest product list of each label source for each ingredient, and whether it was read to its end (0091).';

alter table public.spc_listing enable row level security;
drop policy if exists spc_listing_read on public.spc_listing;
create policy spc_listing_read on public.spc_listing for select to authenticated using (my_role() is not null);
revoke all on public.spc_listing from public, anon;
revoke insert, update, delete, truncate on public.spc_listing from authenticated;
grant select on public.spc_listing to authenticated;

-- ───────────────────────────── one label source's counts ─────────────────────────────
-- p_ingredient null: every ingredient.
create or replace function label_watch_source(p_source text, p_ingredient uuid) returns jsonb
language sql stable security definer set search_path = public as $$
  with prod as (
    select sp.id, sp.product_name, sp.national_id, sp.last_error, sp.last_error_at, sp.checked_at,
           exists (select 1 from spc_snapshot ss where ss.spc_product_id = sp.id) as has_label
      from spc_product sp
     where sp.source_id = p_source and sp.active
       and (p_ingredient is null or sp.ingredient_id = p_ingredient)
  ), lists as (
    select l.* from spc_listing l
     where l.source_id = p_source and (p_ingredient is null or l.ingredient_id = p_ingredient)
  ), last_run as (
    select sr.finished_at, sr.error, source_run_failed(sr.error) as failed
      from source_run sr
     where sr.source_id = p_source and sr.finished_at is not null
     order by sr.started_at desc
     limit 1
  )
  select jsonb_build_object(
    'source_id',     s.id,
    'enabled',       s.enabled,
    'health',        s.health,
    'products',      (select count(*) from prod),
    'labels_read',   (select count(*) from prod where has_label),
    'unread',        (select count(*) from prod where last_error is not null),
    'waiting',       (select count(*) from prod where not has_label and last_error is null),
    'errors',        coalesce((select jsonb_agg(jsonb_build_object(
                                 'product', product_name, 'national_id', national_id,
                                 'error', last_error, 'at', last_error_at)
                               order by last_error_at desc nulls last, product_name)
                                 from (select * from prod where last_error is not null
                                        order by last_error_at desc nulls last, product_name limit 20) e),
                              '[]'::jsonb),
    'last_checked_at', (select max(checked_at) from prod),
    'latest_label_date', (select max(ss.doc_date) from spc_snapshot ss join prod on prod.id = ss.spc_product_id),
    'latest_change_at',  (select max(sc.created_at) from spc_change sc join prod on prod.id = sc.spc_product_id),
    'listed_at',     (select max(listed_at) from lists),
    'lists',         (select count(*) from lists),
    'lists_broken',  (select count(*) from lists where not complete),
    'gaps',          (select string_agg(gaps, '; ' order by listed_at desc) from lists where not complete),
    'last_run',      (select to_jsonb(lr) from last_run lr))
  from source s
  where s.id = p_source;
$$;
revoke all on function label_watch_source(text, uuid) from public, anon, authenticated;

-- ───────────────────────────── the screen: every database page for one ingredient ─────────────────────────────
create or replace function label_watch(p_ingredient uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the label watch.' using errcode = '42501';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = 'P0002';
  end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'page_id', p.id,
             'regulator_id', p.regulator_id,
             'regulator', coalesce(r.name, p.regulator_id),
             'country_name', r.country_name,
             'country_code', r.country_code,
             'label', p.label,
             'url', p.url,
             'note', p.note,
             'partial', p.partial,
             'sources', coalesce((select jsonb_agg(label_watch_source(s.id, p_ingredient) order by s.id)
                                    from source s where s.kind = 'spc' and s.id = any(p.read_by)), '[]'::jsonb))
           order by coalesce(r.country_name, p.regulator_id), p.sort)
      from regulator_page p
      left join regulator r on r.id = p.regulator_id
     where p.kind = 'database'), '[]'::jsonb);
end $$;
revoke all on function label_watch(uuid) from public, anon;
grant execute on function label_watch(uuid) to authenticated;

-- ───────────────────────────── the Sources page: every label source, every ingredient ─────────────────────────────
create or replace function label_watch_sources() returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the label watch.' using errcode = '42501';
  end if;
  return coalesce((select jsonb_object_agg(s.id, label_watch_source(s.id, null))
                     from source s where s.kind = 'spc'), '{}'::jsonb);
end $$;
revoke all on function label_watch_sources() from public, anon;
grant execute on function label_watch_sources() to authenticated;
