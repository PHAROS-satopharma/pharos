-- PHAROS CI — our own labels (0027). Runs on the database ci.yml prepared: the people CI Admin (…a1),
-- CI Reader (…b2) and CI Reviewer (…c3) exist.

create function pg_temp.ol_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ol_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

insert into ingredient (id, inn_en, atc_code) values ('00000000-0000-0000-0000-0000000001a1', 'Cilabeline', 'Z99LB01');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ol_refused($q$select save_our_label('00000000-0000-0000-0000-0000000001a1', 'Cilab 8 mg', 'v1', 'en',
  '{"4.4": "Use with care."}')$q$) as ol_reader \gset
reset role;
select pg_temp.ol_assert(:'ol_reader' like '42501%', 'a reader cannot save our label');

select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000c3","role":"authenticated"}', false);
set role authenticated;
select pg_temp.ol_refused($q$select save_our_label('00000000-0000-0000-0000-0000000001a1', 'Cilab 8 mg', 'v1', 'en',
  '{"6.1": "Lactose."}')$q$) as ol_nosafety \gset
select pg_temp.ol_refused($q$select save_our_label('00000000-0000-0000-0000-0000000001a1', 'Cilab 8 mg', 'v1', 'en',
  '{"Warnings": "Text"}')$q$) as ol_badkey \gset
select save_our_label('00000000-0000-0000-0000-0000000001a1', 'Cilab 8 mg', 'Leaflet 2023', 'en',
  '{"4.4": "Use with care in renal impairment.", "4.8": "Nausea."}', 'leaflet-2023.pdf') as ol1 \gset
select save_our_label('00000000-0000-0000-0000-0000000001a1', ' cilab 8 MG ', 'Leaflet 2025', 'en',
  '{"4.4": "Use with care in renal or hepatic impairment.", "4.8": "Nausea."}') as ol2 \gset
select pg_temp.ol_refused(format($q$update our_label set version = 'edited' where id = %L$q$, :'ol2')) as ol_edit \gset
reset role;
select pg_temp.ol_assert(:'ol_nosafety' like '%No safety section%', 'a label with no section 4 is refused');
select pg_temp.ol_assert(:'ol_badkey' like '%not a numbered section%', 'a section must be numbered');
select pg_temp.ol_assert((select superseded_at is not null from our_label where id = :'ol1')
    and (select superseded_at is null and uploaded_by = (select id from person where email = 'reviewer@example.test')
           from our_label where id = :'ol2')
    and (select count(*) from our_label where ingredient_id = '00000000-0000-0000-0000-0000000001a1' and superseded_at is null) = 1,
  'a new version of the same product supersedes the old one, which is kept');
select pg_temp.ol_assert(:'ol_edit' is not null and (select version from our_label where id = :'ol2') = 'Leaflet 2025',
  'nobody edits a saved label directly');
