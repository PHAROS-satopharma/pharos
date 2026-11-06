-- PHAROS CI — a label belongs to every ingredient it holds (0079): two ingredients may each keep the same label
-- of one source; one ingredient may not hold it twice. Runs in one transaction that is rolled back at the end.

begin;

create function pg_temp.lo_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.lo_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate;
end $$;

insert into ingredient (id, inn_en, atc_code) values
  ('00000000-0000-0000-0000-00000079a001', 'CI ownerofen', 'Z96ZZ11'),
  ('00000000-0000-0000-0000-00000079a002', 'CI coownerine', 'Z96ZZ12');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-LO-A', 'XO', 'CI Ownerland', 'CI Ownerland Agency', '{en}', 'https://owner.example.test/');
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-lo-spc', 'CI-LO-A', 'spc', 'api', 'https://owner.example.test/spc.json', 'ci', '{en}',
   'https://owner.example.test/products', true);

-- A cold remedy holding both ingredients: each ingredient keeps its own row of the same label.
insert into spc_product (ingredient_id, source_id, country_code, national_id, product_name) values
  ('00000000-0000-0000-0000-00000079a001', 'ci-lo-spc', 'XO', 'LO-COLD-1', 'CI Cold Remedy'),
  ('00000000-0000-0000-0000-00000079a002', 'ci-lo-spc', 'XO', 'LO-COLD-1', 'CI Cold Remedy');
select pg_temp.lo_assert(
  (select count(*) from spc_product where source_id = 'ci-lo-spc' and national_id = 'LO-COLD-1') = 2,
  'one label of one source is kept for each of its two ingredients');

-- The label watch's upsert names the new key: the second read of a label for the same ingredient updates it.
insert into spc_product (ingredient_id, source_id, country_code, national_id, product_name, active)
values ('00000000-0000-0000-0000-00000079a001', 'ci-lo-spc', 'XO', 'LO-COLD-1', 'CI Cold Remedy Tablets', true)
on conflict (source_id, ingredient_id, national_id) do update set product_name = excluded.product_name;
select pg_temp.lo_assert(
  (select product_name from spc_product where source_id = 'ci-lo-spc' and national_id = 'LO-COLD-1'
      and ingredient_id = '00000000-0000-0000-0000-00000079a001') = 'CI Cold Remedy Tablets'
  and (select count(*) from spc_product where source_id = 'ci-lo-spc' and national_id = 'LO-COLD-1') = 2,
  'reading the label again for one ingredient updates that row only');

select pg_temp.lo_assert(
  pg_temp.lo_refused($q$insert into spc_product (ingredient_id, source_id, country_code, national_id, product_name)
      values ('00000000-0000-0000-0000-00000079a002', 'ci-lo-spc', 'XO', 'LO-COLD-1', 'twice')$q$) = '23505',
  'one ingredient cannot hold the same label twice');

rollback;
