-- PHAROS 0079 — a label belongs to every ingredient it holds.
--
-- spc_product was unique on (source_id, national_id), and the label watch's upsert never changed the
-- ingredient: the first ingredient to list a label kept it, and every other ingredient in it never saw it.
-- Live, 6 Nov 2026: Japan's acetaminophen package inserts were filed under ivabradine (100 "products", one of
-- them ivabradine), so paracetamol had none in Japan despite its three codes; a cold remedy holding
-- paracetamol, guaifenesin and phenylephrine would have been watched for one of the three.
--
-- Now one row per (source, ingredient, label). Rows already filed under the wrong ingredient are left as they
-- are: that ingredient's next run no longer lists them and marks them inactive, and the right ingredient's run
-- adds its own row. Nothing is deleted.

do $$
declare c text;
begin
  select con.conname into c
    from pg_constraint con
   where con.conrelid = 'public.spc_product'::regclass and con.contype = 'u'
     and (select array_agg(a.attname::text order by a.attname)
            from unnest(con.conkey) k join pg_attribute a
              on a.attrelid = con.conrelid and a.attnum = k) = array['national_id', 'source_id'];
  if c is not null then
    execute format('alter table public.spc_product drop constraint %I', c);
  end if;
end $$;

alter table public.spc_product
  add constraint spc_product_source_ingredient_label_key unique (source_id, ingredient_id, national_id);
