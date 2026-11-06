-- PHAROS CI — the NCBI literature searches the collector has run (0035). Runs on the database ci.yml prepared:
-- CI Reader (…b2) exists. The collector's own statements are tested in tests/test_store_pg.py.

create function pg_temp.ls_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.ls_refused(sql text) returns text language plpgsql as $$
begin
  execute sql;
  return null;
exception when others then
  return sqlstate || ' ' || sqlerrm;
end $$;

-- The collector (the database owner) records a search.
insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('pmc', 'ci levofloxacin', 'name', '2025-11-06', '2026-11-06');

select pg_temp.ls_refused($q$insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('medline', 'ci x', 'name', '2025-11-06', '2026-11-06')$q$) as ls_db \gset
select pg_temp.ls_refused($q$insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('pubmed', 'CI Levofloxacin', 'name', '2025-11-06', '2026-11-06')$q$) as ls_case \gset
select pg_temp.ls_refused($q$insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('pubmed', 'ci y', 'name', '2026-11-06', '2025-11-06')$q$) as ls_dates \gset
select pg_temp.ls_assert(:'ls_db' like '23514%' and :'ls_case' like '23514%' and :'ls_dates' like '23514%',
  'only PubMed or PMC, lower-case words, and a look-back that ends after it starts');

-- A team member reads it and cannot change it.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
select count(*) as ls_reader from literature_search where query = 'ci levofloxacin' \gset
select pg_temp.ls_refused($q$insert into literature_search (db, query, kind, look_back_from, history_until)
  values ('pubmed', 'ci z', 'name', '2025-11-06', '2026-11-06')$q$) as ls_ins \gset
select pg_temp.ls_refused($q$update literature_search set look_back_done_at = now()$q$) as ls_upd \gset
select pg_temp.ls_refused($q$delete from literature_search$q$) as ls_del \gset
reset role;

-- Someone signed in but not on the team reads nothing.
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000ff","role":"authenticated"}', false);
set role authenticated;
select count(*) as ls_stranger from literature_search \gset
reset role;

-- The public key reads nothing.
set role anon;
select pg_temp.ls_refused($q$select count(*) from literature_search$q$) as ls_anon \gset
reset role;

select pg_temp.ls_assert(:ls_reader = 1, 'a team member reads the searches');
select pg_temp.ls_assert(:'ls_ins' like '42501%' and :'ls_upd' like '42501%' and :'ls_del' like '42501%',
  'a team member cannot write, change or remove a search');
select pg_temp.ls_assert(:ls_stranger = 0, 'someone not on the team reads no search');
select pg_temp.ls_assert(:'ls_anon' like '42501%', 'the public key cannot read the searches');
select pg_temp.ls_assert((select look_back_done_at is null and last_searched_at is not null
                            from literature_search where query = 'ci levofloxacin'),
  'a new look-back starts unfinished');

delete from literature_search where query like 'ci %';
