-- PHAROS — an administrator removes an ingredient or a source she added (the owner, 8 Nov 2026: Dr Sama "can add,
-- delete or edit" a source, an ingredient, a product and anything in the system except the people).
--
-- What already held: every administrator right asks for the administrator role only (my_role() = 'admin');
-- person.manages_people (0053) keeps only the People screen from her. She adds and changes ingredients
-- (save_ingredient, ingredient_term), pauses one (ingredient.active), adds a source and switches any source on or
-- off, adds, changes and removes her links (0098), and adds, changes and removes a product (0099). Two removals
-- had no way in the app: an ingredient, and a source she added. Both are made here.
--
-- remove_ingredient(p_id): only a fresh mistake (added, never screened, a misspelt name) is deleted, with its
-- names, classes, people's alerts on it and gathered figures (their foreign keys cascade). One with a record is
-- never deleted, because the record would go with it and most of it is not in the audit log: a notice linked to it,
-- a message sent about it, a signal, a case, a report request, its label watch, our own leaflet, a product it is
-- in, its weekly matching checks (match_audit), clinical trials found for it, or a collection run since it was
-- added (the screening log says it was looked for, even with nothing found). It is paused instead (active =
-- false: no longer looked for, its record kept), and the answer says why.
--
-- remove_source(p_id): a source a person added (origin 'user'). One never read (no run, no document, no e-mail,
-- no label-watch product, no left-out item, no list check) is deleted. Once read it is switched off (enabled =
-- false) and kept with its reads: screening_log() (0040) and screening_summary() (0028) read source_run live, and
-- past weeks and PSUR intervals must keep showing it. A source from the app's own list (origin 'catalogue') is
-- refused: the collector writes it back on every run; it is switched off instead.
--
-- Both are security definer and administrators only (42501), as the screens' other writes, and they are the only
-- way to delete either: 0001's administrator policies are FOR ALL, so the delete privilege on ingredient and
-- source is revoked from signed-in users. Both tables are in the audit log (0001), so a removed row stays readable
-- there.

create function remove_ingredient(p_id uuid) returns jsonb
language plpgsql security definer
set search_path = public as $$
declare
  v_name text;
  v_created timestamptz;
  v_why text[] := '{}';
  n bigint;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can remove an ingredient.' using errcode = '42501';
  end if;
  select inn_en, created_at into v_name, v_created from ingredient where id = p_id for update;
  if not found then
    raise exception 'That ingredient is not on the list.' using errcode = 'P0002';
  end if;

  select count(*) into n from match where ingredient_id = p_id;
  if n > 0 then
    v_why := v_why || format('%s %s linked to it', n, case when n = 1 then 'notice' else 'notices' end);
  end if;
  if exists (select 1 from issue_ingredient where ingredient_id = p_id) then
    v_why := v_why || 'messages sent about it'::text;
  end if;
  if exists (select 1 from signal where ingredient_id = p_id) then v_why := v_why || 'a signal'::text; end if;
  if exists (select 1 from safety_case where ingredient_id = p_id) then v_why := v_why || 'a case report'::text; end if;
  if exists (select 1 from report_request where ingredient_id = p_id) then v_why := v_why || 'a report'::text; end if;
  if exists (select 1 from spc_product where ingredient_id = p_id)
     or exists (select 1 from spc_listing where ingredient_id = p_id) then
    v_why := v_why || 'its label watch'::text;
  end if;
  if exists (select 1 from our_label where ingredient_id = p_id) then v_why := v_why || 'our own leaflet'::text; end if;
  if exists (select 1 from match_audit where ingredient_id = p_id) then
    v_why := v_why || 'its weekly matching checks'::text;
  end if;
  if exists (select 1 from trial_ingredient where ingredient_id = p_id) then
    v_why := v_why || 'clinical trials found for it'::text;
  end if;
  if exists (select 1 from run where started_at > v_created and trigger <> 'probe') then
    v_why := v_why || ('been screened since ' || to_char(v_created at time zone 'Africa/Cairo', 'FMDD Mon YYYY'));
  end if;
  if exists (select 1 from product_ingredient where ingredient_id = p_id) then
    v_why := v_why || ('a product: ' || (select string_agg(p.name, ', ' order by p.name)
                                          from product_ingredient pi join product p on p.id = pi.product_id
                                         where pi.ingredient_id = p_id));
  end if;

  if cardinality(v_why) > 0 then
    update ingredient set active = false where id = p_id and active;
    return jsonb_build_object('outcome', 'paused', 'name', v_name, 'reasons', to_jsonb(v_why));
  end if;
  delete from ingredient where id = p_id;
  return jsonb_build_object('outcome', 'deleted', 'name', v_name, 'reasons', '[]'::jsonb);
end $$;

revoke all on function remove_ingredient(uuid) from public, anon;
grant execute on function remove_ingredient(uuid) to authenticated, service_role;

create function remove_source(p_id text) returns jsonb
language plpgsql security definer
set search_path = public as $$
declare
  v_origin source_origin;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator can remove a source.' using errcode = '42501';
  end if;
  select origin into v_origin from source where id = p_id for update;
  if not found then
    raise exception 'That source is not on the list.' using errcode = 'P0002';
  end if;
  if v_origin <> 'user' then
    raise exception 'This source is on the app''s own list and comes back on the next run: switch it off instead.'
      using errcode = '22023';
  end if;

  if exists (select 1 from source_run where source_id = p_id)
     or exists (select 1 from document where source_id = p_id)
     or exists (select 1 from inbound_email where source_id = p_id)
     or exists (select 1 from spc_product where source_id = p_id)
     or exists (select 1 from spc_listing where source_id = p_id)
     or exists (select 1 from filtered_item where source_id = p_id)
     or exists (select 1 from list_check where source_id = p_id) then
    update source set enabled = false where id = p_id and enabled;
    return jsonb_build_object('outcome', 'switched_off');
  end if;
  delete from source where id = p_id;
  return jsonb_build_object('outcome', 'deleted');
end $$;

revoke all on function remove_source(text) from public, anon;
grant execute on function remove_source(text) to authenticated, service_role;

-- The two functions above are the only way to delete an ingredient or a source.
revoke delete on ingredient, source from authenticated;
