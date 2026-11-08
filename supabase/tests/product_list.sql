-- PHAROS CI — the product list and cases by product (0099). Runs after every migration and the acceptance checks in
-- ci.yml, on the same database: the people CI Admin (…a1), CI Reader (…b2) and CI Reviewer (…c3) exist.

create function pg_temp.ci_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into ingredient (id, inn_en) values
  ('00000000-0000-0000-0000-00000099a001', 'CI carvedilol'),
  ('00000000-0000-0000-0000-00000099a002', 'CI ivabradine'),
  ('00000000-0000-0000-0000-00000099a003', 'CI other');

\set carvexa '''{"name": "CI Carvexa", "mah": "Sato Pharma", "dosage_form": "film-coated tablet", "ingredients": ["00000000-0000-0000-0000-00000099a001", "00000000-0000-0000-0000-00000099a002"], "strengths": [{"parts": [{"ingredient_id": "00000000-0000-0000-0000-00000099a001", "amount": 6.25, "unit": "mg"}, {"ingredient_id": "00000000-0000-0000-0000-00000099a002", "amount": 5, "unit": "mg"}]}, {"parts": [{"ingredient_id": "00000000-0000-0000-0000-00000099a001", "amount": "12.5"}, {"ingredient_id": "00000000-0000-0000-0000-00000099a002", "amount": 7.5}]}]}'''
\set short '''{"name": "CI Short", "ingredients": ["00000000-0000-0000-0000-00000099a001", "00000000-0000-0000-0000-00000099a002"], "strengths": [{"parts": [{"ingredient_id": "00000000-0000-0000-0000-00000099a001", "amount": 6.25}]}]}'''

-- Only an administrator changes the product list.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format('select save_product(%L)', :carvexa)) as r_reader \gset
reset role;
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format('select save_product(%L)', :carvexa)) as r_reviewer \gset
reset role;
select pg_temp.ci_assert(:'r_reader' like '42501%' and :'r_reviewer' like '42501%',
  'a reader and a reviewer cannot change the product list');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select save_product(:carvexa) ->> 'id' as prod \gset
select pg_temp.refused(format('select save_product(%L)', :short)) as r_short \gset
select pg_temp.refused(format('select save_product(%L)', :carvexa)) as r_twice \gset
reset role;
select pg_temp.ci_assert((select active and dosage_form = 'film-coated tablet'
                                 and created_by = (select id from person where email = 'admin@example.test')
                            from product where id = :'prod'),
  'an administrator adds a product, recorded as the person who added it');
select pg_temp.ci_assert((select array_agg(label order by sort) from product_strength where product_id = :'prod')
                           = array['6.25 mg / 5 mg', '12.5 mg / 7.5 mg'],
  'each strength is named from its amounts, in the order given');
select pg_temp.ci_assert(:'r_short' like '%one amount for each ingredient%',
  'a strength gives an amount for every ingredient of the product');
select pg_temp.ci_assert(:'r_twice' like '%already on the list%', 'two products never share a name');

-- The table itself refuses an amount for an ingredient that is not in the product.
select pg_temp.refused(format($q$insert into product_strength_part (strength_id, product_id, ingredient_id, amount)
  select id, product_id, '00000000-0000-0000-0000-00000099a003', 1 from product_strength where product_id = %L limit 1$q$,
  :'prod')) as r_foreign \gset
select pg_temp.ci_assert(:'r_foreign' like '23503%', 'a strength holds only the product''s own ingredients');

select id as s1 from product_strength where product_id = :'prod' and sort = 1 \gset
select id as s2 from product_strength where product_id = :'prod' and sort = 2 \gset

-- A reviewer opens a case for the product and its strength.
\set sha '''bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'''
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format($q$select create_upload_case('p.pdf', 'application/pdf', %L, 100, case_cairo_today(), null, null, %L)$q$, :sha, :'s1')) as r_nostrprod \gset
select pg_temp.refused(format($q$select create_upload_case('p.pdf', 'application/pdf', %L, 100, case_cairo_today(), '00000000-0000-0000-0000-00000099a003', %L, %L)$q$, :sha, :'prod', :'s1')) as r_wrongi \gset
select create_upload_case('Carvexa report.pdf', 'application/pdf', :sha, 2048, case_cairo_today() - 1, null, :'prod', :'s1') as pc \gset
reset role;
select pg_temp.ci_assert(:'r_nostrprod' like '%Choose the product of this strength%', 'a strength needs its product');
select pg_temp.ci_assert(:'r_wrongi' like '%not in the product%', 'the ingredient of a product case is one of the product''s');
select pg_temp.ci_assert((select product_id = :'prod' and product_strength_id = :'s1' and ingredient_id is null
                            from safety_case where id = :'pc'),
  'a case of a combination product keeps the product and its strength, with no single ingredient');
select pg_temp.ci_assert((select product = 'CI Carvexa 6.25 mg / 5 mg' from v_case_table where id = :'pc'),
  'the list of cases shows the product with its strength');

-- The collector reads it; the reviewer confirms it with the product and no ingredient.
update safety_case set status = 'to_confirm', updated_at = now(),
       data = '{"patient": {"initials": "S.K."}, "reporter": {"qualification": "physician"}, "products": [{"name": "CI Carvexa 6.25 mg / 5 mg", "role": "suspect", "ingredients": [{"name": "CI carvedilol", "amount": 6.25, "unit": "mg"}, {"name": "CI ivabradine", "amount": 5, "unit": "mg"}]}], "reactions": [{"verbatim": "bradycardia", "mesh_ui": "D001919"}]}'
 where id = :'pc';
select updated_at as seen1, data::text as form1 from safety_case where id = :'pc' \gset
set role authenticated;
select pg_temp.refused(format($q$select confirm_case(%L, %L, %L, true, null)$q$, :'pc', :'seen1', :'form1')) as r_neither \gset
select pg_temp.refused(format($q$select confirm_case(%L, %L, %L, true, null, null, %L, %L)$q$, :'pc', :'seen1', :'form1', :'prod', :'s1'::text || 'x')) as r_badstr \gset
select pg_temp.refused(format($q$select save_case(%L, %L, '{"products": [{"name": "x", "ingredients": "6.25 mg"}]}', true, null, null, %L)$q$, :'pc', :'seen1', :'prod')) as r_shape \gset
select confirm_case(:'pc', :'seen1', :'form1', true, null, 'Checked', :'prod', :'s2') as seen2 \gset
reset role;
select pg_temp.ci_assert(:'r_neither' like '%Choose the ingredient or the product%',
  'a confirmed case names its product or its ingredient');
select pg_temp.ci_assert(:'r_badstr' is not null, 'a strength that does not exist is refused');
select pg_temp.ci_assert(:'r_shape' like '%products of the case form are not valid%',
  'a product''s ingredients are a list');
select pg_temp.ci_assert((select status = 'confirmed' and product_id = :'prod' and product_strength_id = :'s2'
                            from safety_case where id = :'pc'),
  'a case is confirmed with its product and the strength the reviewer chose');

-- The case counts on the page of each ingredient of its product.
select pg_temp.ci_assert((select count(*) from ingredient_coded_terms('00000000-0000-0000-0000-00000099a001')
                           where kind = 'case' and item = :'pc') = 1
                         and (select count(*) from ingredient_coded_terms('00000000-0000-0000-0000-00000099a002')
                               where kind = 'case' and item = :'pc') = 1
                         and (select count(*) from ingredient_coded_terms('00000000-0000-0000-0000-00000099a003')
                               where kind = 'case' and item = :'pc') = 0,
  'a product''s case counts for each of its ingredients, and for no other');

-- A strength a case names stays; a product a case names is archived, an unused one deleted.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format($q$select save_product(jsonb_set(%L::jsonb, '{id}', to_jsonb(%L::text)) - 'strengths'
  || jsonb_build_object('strengths', jsonb_build_array(jsonb_build_object('id', %L::text, 'parts',
       '[{"ingredient_id": "00000000-0000-0000-0000-00000099a001", "amount": 6.25}, {"ingredient_id": "00000000-0000-0000-0000-00000099a002", "amount": 5}]'::jsonb))))$q$,
  :carvexa, :'prod', :'s1')) as r_dropused \gset
select save_product(jsonb_build_object('id', :'prod', 'remove', true)) ->> 'outcome' as removed \gset
select save_product('{"name": "CI Lonely", "ingredients": ["00000000-0000-0000-0000-00000099a003"], "strengths": [{"label": "8 mg", "parts": [{"ingredient_id": "00000000-0000-0000-0000-00000099a003", "amount": 8}]}]}') ->> 'id' as lonely \gset
select save_product(jsonb_build_object('id', :'lonely', 'remove', true)) ->> 'outcome' as removed2 \gset
reset role;
select pg_temp.ci_assert(:'r_dropused' like '%strength a case names%', 'a strength a case names is never removed');
select pg_temp.ci_assert(:'removed' = 'archived' and (select not active from product where id = :'prod'),
  'a product a case names is archived, not deleted');
select pg_temp.ci_assert(:'removed2' = 'deleted' and not exists (select 1 from product where id = :'lonely'),
  'a product no case names is deleted with its strengths');

-- An archived product cannot be picked for a new case.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.refused(format($q$select create_upload_case('q.pdf', 'application/pdf', %L, 100, case_cairo_today(), null, %L)$q$, :sha, :'prod')) as r_archived \gset
reset role;
select pg_temp.ci_assert(:'r_archived' like '%archived%', 'an archived product is not offered for a new case');
