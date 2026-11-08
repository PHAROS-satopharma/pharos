-- PHAROS — the product list, and cases by product (2026-11-08).
--
-- Dr Sama's feedback of 8 November 2026: a case is reported against a PRODUCT, and one of ours can combine several
-- active ingredients (carvedilol + ivabradine), each in its own amount per strength (6.25 mg / 5 mg). The product
-- list lives on its own tab beside Ingredients; on Cases → New case and on the case itself she picks the whole
-- product and its strength, and the suspect drug line of the form is filled with the product's name, the strength
-- and every ingredient with its amount. The literature, the label watch, the weekly report and the readiness stay
-- per ingredient: a product is watched through each of its ingredients, as 0001 already said.
--
-- What changes:
--   product            gains dosage_form, active (an archived product stays for the cases that name it) and
--                      created_by; product and product_ingredient keep 0001's policies and audit triggers;
--   product_strength   one strength of a product, with its label ("6.25 mg / 5 mg") and order;
--   product_strength_part
--                      the amount and unit of each ingredient in a strength. Its ingredient must be one of the
--                      product's: a foreign key to product_ingredient, through the strength's own product;
--   save_product(p)    an administrator adds or changes a product with its ingredients and strengths in one call, or
--                      removes it: a product a case names is archived (active = false), never deleted;
--   safety_case        gains product_id and product_strength_id (the strength must be the product's); the case
--                      functions take p_product and p_strength, and a case is confirmed with a product OR an
--                      ingredient. A product of one ingredient also sets the case's ingredient;
--   v_case_table       shows the product with its strength;
--   ingredient_coded_terms counts a case for each ingredient of its product, so the signal counts on an
--                      ingredient's page include the cases of every product that contains it.

-- ───────────────────────────── the product list ─────────────────────────────
alter table product
  add column dosage_form text,
  add column active      boolean not null default true,
  add column created_by  uuid references person(id);
-- The name rules below would stop the deploy half-way on rows that break them. Nothing has written product before
-- this migration (0001 made the table; no app screen, function or collector inserts into it), but a row added by
-- hand would: the deploy stops here first and names the rows to fix.
do $$
declare v_bad text;
begin
  select string_agg(format('%s (%s)', coalesce(nullif(trim(name), ''), '<no name>'), id), '; ' order by name)
    into v_bad
    from product p
   where length(trim(coalesce(p.name, ''))) = 0
      or exists (select 1 from product o where o.id <> p.id and lower(trim(o.name)) = lower(trim(p.name)));
  if v_bad is not null then
    raise exception 'Products with no name or one name twice (fix or merge them, then deploy again): %', v_bad;
  end if;
end $$;
create unique index product_name_unique on product (lower(trim(name)));
alter table product add constraint product_name_given check (length(trim(name)) > 0);

create table product_strength (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references product(id) on delete cascade,
  label       text not null check (length(trim(label)) > 0),
  sort        int not null default 0,
  created_at  timestamptz not null default now(),
  unique (id, product_id),
  unique (product_id, label)
);

create table product_strength_part (
  strength_id    uuid not null,
  product_id     uuid not null,
  ingredient_id  uuid not null,
  amount         numeric not null check (amount > 0),
  unit           text not null default 'mg' check (unit in ('mg','g','µg','mL','IU','%')),
  primary key (strength_id, ingredient_id),
  -- The strength is the product's, and the ingredient is one of the product's.
  foreign key (strength_id, product_id) references product_strength (id, product_id) on delete cascade,
  foreign key (product_id, ingredient_id) references product_ingredient (product_id, ingredient_id) on delete cascade
);

create trigger audit_product_strength after insert or update or delete on product_strength
  for each row execute function audit_row();
create trigger audit_product_strength_part after insert or update or delete on product_strength_part
  for each row execute function audit_row();

alter table product_strength      enable row level security;
alter table product_strength_part enable row level security;
create policy product_strength_read on product_strength for select to authenticated using (my_role() is not null);
create policy product_strength_part_read on product_strength_part for select to authenticated
  using (my_role() is not null);
create policy product_strength_admin on product_strength for all to authenticated
  using (my_role() = 'admin') with check (my_role() = 'admin');
create policy product_strength_part_admin on product_strength_part for all to authenticated
  using (my_role() = 'admin') with check (my_role() = 'admin');
revoke insert, update, delete, truncate on product_strength, product_strength_part from anon;

-- A strength's label from its parts, in the order of the product's ingredients by name: "6.25 mg / 5 mg".
create function product_strength_label(p_strength uuid) returns text language sql stable
set search_path = public as $$
  select string_agg(trim_scale(sp.amount)::text || ' ' || sp.unit, ' / ' order by i.inn_en)
    from product_strength_part sp
    join ingredient i on i.id = sp.ingredient_id
   where sp.strength_id = p_strength
$$;

-- ───────────────────────────── save_product ─────────────────────────────
-- p: {id?, name, mah?, dosage_form?, active?, ingredients: [ingredient id, …],
--     strengths: [{id?, label?, parts: [{ingredient_id, amount, unit?}, …]}, …]}
-- or {id, remove: true}. Every strength gives an amount for each of the product's ingredients; a strength
-- without a label is named from its amounts. A strength a case uses is never removed (the case keeps it).
-- Answers {id, outcome}: outcome is saved, archived (a case names it) or deleted.
create function save_product(p jsonb) returns jsonb language plpgsql security definer
set search_path = public as $$
declare
  v_person   uuid := my_person_id();
  v_id       uuid := nullif(p ->> 'id', '')::uuid;
  v_name     text := trim(coalesce(p ->> 'name', ''));
  v_ings     uuid[];
  v_s        jsonb;
  v_part     jsonb;
  v_sid      uuid;
  v_keep     uuid[] := '{}';
  v_sort     int := 0;
  v_unit     text;
  v_amount   numeric;
  v_label    text;
  v_n        int;
  v_old      text;
begin
  if v_person is null or my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can change the product list.' using errcode = '42501';
  end if;
  if p is null or jsonb_typeof(p) <> 'object' then
    raise exception 'The product is not valid.' using errcode = '22023';
  end if;
  if v_id is not null and not exists (select 1 from product where id = v_id) then
    raise exception 'That product does not exist.' using errcode = '22023';
  end if;

  -- Remove: archived when a case names it, else deleted with its strengths.
  if coalesce((p ->> 'remove')::boolean, false) then
    if v_id is null then raise exception 'Say which product to remove.' using errcode = '22023'; end if;
    if exists (select 1 from safety_case where product_id = v_id) then
      update product set active = false where id = v_id;
      return jsonb_build_object('id', v_id, 'outcome', 'archived');
    end if;
    delete from product where id = v_id;
    return jsonb_build_object('id', v_id, 'outcome', 'deleted');
  end if;

  if v_name = '' then raise exception 'Give the product''s name.' using errcode = '22023'; end if;
  if length(v_name) > 200 then raise exception 'The product''s name is at most 200 characters.' using errcode = '22023'; end if;
  if jsonb_typeof(p -> 'ingredients') is distinct from 'array' then
    raise exception 'Choose the product''s ingredients.' using errcode = '22023';
  end if;
  select coalesce(array_agg(distinct x::uuid), '{}') into v_ings from jsonb_array_elements_text(p -> 'ingredients') x;
  if cardinality(v_ings) = 0 then raise exception 'Choose the product''s ingredients.' using errcode = '22023'; end if;
  if (select count(*) from ingredient where id = any(v_ings)) <> cardinality(v_ings) then
    raise exception 'An ingredient of the product is not on the watchlist.' using errcode = '22023';
  end if;
  if jsonb_typeof(p -> 'strengths') is distinct from 'array' or jsonb_array_length(p -> 'strengths') = 0 then
    raise exception 'Give at least one strength.' using errcode = '22023';
  end if;
  if exists (select 1 from product where lower(trim(name)) = lower(v_name) and id is distinct from v_id) then
    raise exception 'A product named % is already on the list.', v_name using errcode = '23505';
  end if;

  if v_id is null then
    insert into product (name, mah, dosage_form, active, created_by)
    values (v_name, nullif(trim(p ->> 'mah'), ''), nullif(trim(p ->> 'dosage_form'), ''),
            coalesce((p ->> 'active')::boolean, true), v_person)
    returning id into v_id;
  else
    update product set name = v_name, mah = nullif(trim(p ->> 'mah'), ''),
                       dosage_form = nullif(trim(p ->> 'dosage_form'), ''),
                       active = coalesce((p ->> 'active')::boolean, active)
     where id = v_id;
  end if;

  -- A product a case names keeps its ingredients: the case's suspect drug was that combination.
  if exists (select 1 from safety_case where product_id = v_id)
     and exists (select 1 from product_ingredient where product_id = v_id and not (ingredient_id = any(v_ings))) then
    raise exception 'A case names this product: its ingredients cannot be taken off. Add a new product instead.'
      using errcode = '22023';
  end if;

  -- The ingredients: an ingredient taken off the product takes its amounts with it (the strengths are rebuilt).
  delete from product_ingredient where product_id = v_id and not (ingredient_id = any(v_ings));
  insert into product_ingredient (product_id, ingredient_id)
  select v_id, x from unnest(v_ings) x
  on conflict do nothing;

  -- The strengths, in the order given. The ones there now are first named by their id, so a strength may take
  -- the label another one had (the ones left off the list are removed below).
  update product_strength set label = id::text where product_id = v_id;
  for v_s in select * from jsonb_array_elements(p -> 'strengths') loop
    v_sort := v_sort + 1;
    if jsonb_typeof(v_s -> 'parts') is distinct from 'array' then
      raise exception 'Strength % gives no amounts.', v_sort using errcode = '22023';
    end if;
    select count(distinct (e ->> 'ingredient_id')) into v_n
      from jsonb_array_elements(v_s -> 'parts') e
     where (e ->> 'ingredient_id')::uuid = any(v_ings);
    if v_n <> cardinality(v_ings) or jsonb_array_length(v_s -> 'parts') <> cardinality(v_ings) then
      raise exception 'Strength % needs one amount for each ingredient of the product.', v_sort using errcode = '22023';
    end if;
    v_sid := nullif(v_s ->> 'id', '')::uuid;
    if v_sid is not null and not exists (select 1 from product_strength where id = v_sid and product_id = v_id) then
      raise exception 'Strength % is not one of this product''s.', v_sort using errcode = '22023';
    end if;
    if v_sid is null then
      insert into product_strength (product_id, label, sort)
      values (v_id, 'strength ' || gen_random_uuid()::text, v_sort)   -- named from its parts below
      returning id into v_sid;
    else
      update product_strength set sort = v_sort where id = v_sid;
      -- A strength a case names keeps its amounts (checked once the new ones are in, below).
      select string_agg(ingredient_id || ':' || trim_scale(amount) || ' ' || unit, ',' order by ingredient_id)
        into v_old from product_strength_part where strength_id = v_sid;
      delete from product_strength_part where strength_id = v_sid;
    end if;
    for v_part in select * from jsonb_array_elements(v_s -> 'parts') loop
      begin
        v_amount := (v_part ->> 'amount')::numeric;
      exception when others then
        v_amount := null;
      end;
      if v_amount is null or v_amount <= 0 then
        raise exception 'Strength % needs an amount above zero for each ingredient.', v_sort using errcode = '22023';
      end if;
      v_unit := coalesce(nullif(trim(v_part ->> 'unit'), ''), 'mg');
      if v_unit not in ('mg','g','µg','mL','IU','%') then
        raise exception 'The unit % is not one PHAROS knows: mg, g, µg, mL, IU or %%.', v_unit using errcode = '22023';
      end if;
      insert into product_strength_part (strength_id, product_id, ingredient_id, amount, unit)
      values (v_sid, v_id, (v_part ->> 'ingredient_id')::uuid, v_amount, v_unit);
    end loop;
    if exists (select 1 from safety_case where product_strength_id = v_sid)
       and v_old is distinct from (select string_agg(ingredient_id || ':' || trim_scale(amount) || ' ' || unit, ','
                                                     order by ingredient_id)
                                     from product_strength_part where strength_id = v_sid) then
      raise exception 'A case names strength %: its amounts cannot change. Add a new strength instead.', v_sort
        using errcode = '22023';
    end if;
    v_old := null;
    v_label := coalesce(nullif(trim(v_s ->> 'label'), ''), product_strength_label(v_sid));
    if exists (select 1 from product_strength where product_id = v_id and label = v_label and id <> v_sid) then
      raise exception 'Two strengths of the product are both %.', v_label using errcode = '23505';
    end if;
    update product_strength set label = left(v_label, 200) where id = v_sid;
    v_keep := v_keep || v_sid;
  end loop;

  -- A strength left off the list goes, unless a case names it.
  if exists (select 1 from safety_case c join product_strength s on s.id = c.product_strength_id
              where s.product_id = v_id and not (s.id = any(v_keep))) then
    raise exception 'A strength a case names cannot be taken off the product. Keep it on the list.'
      using errcode = '22023';
  end if;
  delete from product_strength where product_id = v_id and not (id = any(v_keep));
  return jsonb_build_object('id', v_id, 'outcome', 'saved');
end $$;

revoke all on function save_product(jsonb) from public, anon;
grant execute on function save_product(jsonb) to authenticated;
revoke all on function product_strength_label(uuid) from public, anon;
grant execute on function product_strength_label(uuid) to authenticated;

-- ───────────────────────────── cases by product ─────────────────────────────
alter table safety_case
  add column product_id           uuid references product(id),
  add column product_strength_id  uuid,
  add constraint safety_case_strength_of_product
    foreign key (product_strength_id, product_id) references product_strength (id, product_id),
  add constraint safety_case_strength_needs_product check (product_strength_id is null or product_id is not null);
create index on safety_case (product_id);

-- The product and strength a reviewer picked, checked; answers the ingredient the case keeps: the one given, or
-- the product's own when it has a single ingredient. A product archived since stays on the case that names it.
create function case_check_product(p_product uuid, p_strength uuid, p_ingredient uuid, p_current uuid default null)
returns uuid language plpgsql stable security definer set search_path = public as $$
declare
  v_active boolean;
  v_single uuid;
begin
  if p_strength is not null and p_product is null then
    raise exception 'Choose the product of this strength.' using errcode = '22023';
  end if;
  if p_product is null then return p_ingredient; end if;
  select active into v_active from product where id = p_product;
  if v_active is null then
    raise exception 'That product is not on the product list.' using errcode = '22023';
  end if;
  if not v_active and p_product is distinct from p_current then
    raise exception 'That product is archived. Choose one on the product list.' using errcode = '22023';
  end if;
  if p_strength is not null and not exists (select 1 from product_strength where id = p_strength and product_id = p_product) then
    raise exception 'That strength is not one of the product''s.' using errcode = '22023';
  end if;
  if p_ingredient is not null then
    if not exists (select 1 from product_ingredient where product_id = p_product and ingredient_id = p_ingredient) then
      raise exception 'That ingredient is not in the product.' using errcode = '22023';
    end if;
    return p_ingredient;
  end if;
  select case when count(*) = 1 then min(ingredient_id::text)::uuid end into v_single
    from product_ingredient where product_id = p_product;
  return v_single;
end $$;

-- The form's shape, as 0059, and each product's ingredients (an array of {name, amount, unit}) when it has them.
create or replace function case_check_form(p_data jsonb, p_ingredient uuid) returns void language plpgsql stable
security definer set search_path = public as $$
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'The case form is not valid.' using errcode = '22023';
  end if;
  if octet_length(p_data::text) > 200000 then
    raise exception 'The case form is too long.' using errcode = '22023';
  end if;
  if p_ingredient is not null and not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = '22023';
  end if;
  if jsonb_typeof(p_data -> 'products') = 'array' and exists (
       select 1 from jsonb_array_elements(p_data -> 'products') e
        where jsonb_typeof(e) <> 'object'
           or (e ? 'ingredients' and jsonb_typeof(e -> 'ingredients') not in ('array','null'))) then
    raise exception 'The products of the case form are not valid.' using errcode = '22023';
  end if;
end $$;

drop function create_upload_case(text, text, text, int, date, uuid);
create function create_upload_case(p_file_name text, p_mime text, p_sha256 text, p_bytes int, p_day_zero date,
                                   p_ingredient uuid default null, p_product uuid default null,
                                   p_strength uuid default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v_id     uuid;
  v_name   text := nullif(left(trim(coalesce(p_file_name, '')), 200), '');
  v_ing    uuid;
begin
  if p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'The file''s SHA-256 is not valid.' using errcode = '22023';
  end if;
  if p_mime is null or p_mime not in ('application/pdf','image/png','image/jpeg','image/gif','image/webp','message/rfc822','text/plain',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document') then
    raise exception 'PHAROS reads PDF, photos (PNG, JPEG, GIF, WebP), Word (.docx), saved emails (.eml) and text files.'
      using errcode = '22023';
  end if;
  if p_bytes is null or p_bytes <= 0 or p_bytes > 10 * 1024 * 1024 then
    raise exception 'A case document is at most 10 MB.' using errcode = '22023';
  end if;
  if p_day_zero is null or p_day_zero > case_cairo_today() or p_day_zero < case_cairo_today() - 366 then
    raise exception 'Day zero is the day the company received the report: today or within the last year.'
      using errcode = '22023';
  end if;
  perform case_check_form('{}'::jsonb, p_ingredient);
  v_ing := case_check_product(p_product, p_strength, p_ingredient);

  insert into safety_case (ref, origin, status, ingredient_id, product_id, product_strength_id, file_name, mime,
                           sha256, r2_key, bytes, day_zero, created_by)
  values (case_new_ref(), 'upload', 'queued', v_ing, p_product, p_strength, coalesce(v_name, 'document'), p_mime,
          p_sha256, 'sha256/' || left(p_sha256, 2) || '/' || p_sha256, p_bytes, p_day_zero, v_person)
  returning id into v_id;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (v_id, 'received', null, 'queued', coalesce(v_name, 'document'), v_person);
  return v_id;
end $$;

drop function save_case(uuid, timestamptz, jsonb, boolean, uuid, text);
create function save_case(p_case uuid, p_seen timestamptz, p_data jsonb, p_serious boolean, p_ingredient uuid,
                          p_comment text, p_product uuid, p_strength uuid)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v        safety_case%rowtype := case_lock(p_case, p_seen);
  v_now    timestamptz := clock_timestamp();
  v_ing    uuid;
begin
  if v.status not in ('to_confirm','failed') then
    raise exception 'Only a case waiting for confirmation can be changed. Reopen it first.' using errcode = '22023';
  end if;
  perform case_check_form(p_data, p_ingredient);
  v_ing := case_check_product(p_product, p_strength, p_ingredient, v.product_id);
  update safety_case set data = p_data, serious = p_serious, ingredient_id = v_ing, product_id = p_product,
                         product_strength_id = p_strength, status = 'to_confirm', updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, data, person_id)
  values (p_case, 'saved', v.status, 'to_confirm', nullif(trim(p_comment), ''), p_data, v_person);
  return v_now;
end $$;

-- Confirms the case: the four minimum criteria, a product or an ingredient, and the seriousness.
drop function confirm_case(uuid, timestamptz, jsonb, boolean, uuid, text);
create function confirm_case(p_case uuid, p_seen timestamptz, p_data jsonb, p_serious boolean, p_ingredient uuid,
                             p_comment text, p_product uuid, p_strength uuid)
returns timestamptz language plpgsql security definer set search_path = public as $$
declare
  v_person  uuid := case_require_reviewer();
  v         safety_case%rowtype := case_lock(p_case, p_seen);
  v_missing text[];
  v_now     timestamptz := clock_timestamp();
  v_ing     uuid;
begin
  if v.status not in ('to_confirm','failed') then
    raise exception 'Only a case waiting for confirmation can be confirmed.' using errcode = '22023';
  end if;
  perform case_check_form(p_data, p_ingredient);
  v_missing := case_missing(p_data);
  if cardinality(v_missing) > 0 then
    raise exception 'Not a valid case yet: % missing.', array_to_string(v_missing, ', ') using errcode = '22023';
  end if;
  if p_ingredient is null and p_product is null then
    raise exception 'Choose the ingredient or the product the case is about.' using errcode = '22023';
  end if;
  v_ing := case_check_product(p_product, p_strength, p_ingredient, v.product_id);
  if p_serious is null then
    raise exception 'Say whether the case is serious.' using errcode = '22023';
  end if;
  update safety_case set data = p_data, serious = p_serious, ingredient_id = v_ing, product_id = p_product,
                         product_strength_id = p_strength, status = 'confirmed',
                         confirmed_by = v_person, confirmed_at = v_now, updated_at = v_now
   where id = p_case;
  insert into case_event (case_id, step, from_status, to_status, comment, data, person_id)
  values (p_case, 'confirmed', v.status, 'confirmed', nullif(trim(p_comment), ''), p_data, v_person);
  return v_now;
end $$;

revoke all on function case_check_product(uuid, uuid, uuid, uuid), case_check_form(jsonb, uuid),
  create_upload_case(text, text, text, int, date, uuid, uuid, uuid),
  save_case(uuid, timestamptz, jsonb, boolean, uuid, text, uuid, uuid),
  confirm_case(uuid, timestamptz, jsonb, boolean, uuid, text, uuid, uuid)
  from public, anon;
grant execute on function
  create_upload_case(text, text, text, int, date, uuid, uuid, uuid),
  save_case(uuid, timestamptz, jsonb, boolean, uuid, text, uuid, uuid),
  confirm_case(uuid, timestamptz, jsonb, boolean, uuid, text, uuid, uuid)
  to authenticated;
-- A checker the case functions call (as their owner), never a caller: Supabase's default privileges grant every
-- new function to authenticated, and this one is security definer with no role check of its own.
revoke all on function case_check_product(uuid, uuid, uuid, uuid) from authenticated;

-- ───────────────────────────── the list of cases ─────────────────────────────
-- 0059's columns unchanged; the product and its strength are added at the end.
create or replace view v_case_table with (security_invoker = true) as
select
  c.id, c.ref, c.origin, c.status, c.ingredient_id,
  ing.inn_en                                                        as ingredient,
  c.file_name, c.day_zero, c.serious,
  case_due(c.day_zero, c.serious)                                   as due,
  (c.status in ('queued','reading','to_confirm','failed','confirmed')
   and case_due(c.day_zero, c.serious) < case_cairo_today())         as overdue,
  c.sent_on, c.authority_ref,
  nullif(concat_ws(' · ', c.data #>> '{patient,initials}',
                   nullif(concat_ws(' ', c.data #>> '{patient,age_value}', c.data #>> '{patient,age_unit}'), ''),
                   c.data #>> '{patient,sex}'), '')                  as patient,
  (select string_agg(e ->> 'verbatim', '; ')
     from jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                    then c.data -> 'reactions' else '[]'::jsonb end) e)  as reactions,
  case_missing(c.data)                                              as missing,
  c.e2b_status, c.created_at, c.updated_at,
  c.product_id, c.product_strength_id,
  nullif(concat_ws(' ', pr.name, ps.label), '')                     as product
from safety_case c
left join ingredient ing on ing.id = c.ingredient_id
left join product pr on pr.id = c.product_id
left join product_strength ps on ps.id = c.product_strength_id;

-- ───────────────────────────── the coded reactions of an ingredient ─────────────────────────────
-- As 0062/0064, and a case counts for an ingredient also when its product contains it.
create or replace function ingredient_coded_terms(p_ingredient uuid)
returns table (kind text, item uuid, ui text, day date) language sql stable security definer
set search_path = public as $$
  select 'case', c.id, r ->> 'mesh_ui', c.day_zero
    from safety_case c,
         jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                   then c.data -> 'reactions' else '[]'::jsonb end) r
   where (c.ingredient_id = p_ingredient
          or exists (select 1 from product_ingredient pi
                      where pi.product_id = c.product_id and pi.ingredient_id = p_ingredient))
     and c.status in ('to_confirm','confirmed','sent')
     and coalesce(r ->> 'mesh_ui', '') <> ''
  union
  select 'paper', d.id, m ->> 'ui', coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date)
    from issue_ingredient ii
    join issue_document idoc on idoc.issue_id = ii.issue_id and idoc.method <> 'suggested'
    join document d on d.id = idoc.document_id and d.doc_type = 'literature'
    cross join lateral jsonb_array_elements(case when jsonb_typeof(d.structured -> 'mesh') = 'array'
                                                 then d.structured -> 'mesh' else '[]'::jsonb end) m
    join mesh_descriptor md on md.ui = m ->> 'ui'
   where ii.ingredient_id = p_ingredient
     and (coalesce(m -> 'q', '[]'::jsonb) ? 'Q000139'
          or exists (select 1 from unnest(md.trees) t where t like 'C25%'))
$$;
