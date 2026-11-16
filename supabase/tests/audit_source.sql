-- PHAROS CI — the database stops growing by audit rows that record no change (0116): an update that changes
-- nothing is not logged on any audited table; a source is logged when the source itself changes, not when the
-- collector writes last_ok_at, consecutive_failures or last_item_at; the day's size is kept. Everything happens in
-- one transaction that is rolled back at the end.

begin;

create function pg_temp.as_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

create function pg_temp.as_count(p_action text) returns bigint language sql as $$
  select count(*) from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = p_action
$$;

insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-AS', 'XA', 'CI Auditland', 'CI Audit Agency', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, enabled, origin) values
  ('ci-as-feed', 'CI-AS', 'safety', 'rss', 'https://as.example.test/feed', 'feed', '{en}', true, 'catalogue');

select pg_temp.as_assert(pg_temp.as_count('INSERT') = 1, 'adding a source is in the audit log');

-- ───────────── an update that changes nothing: not logged ─────────────
-- What Store.set_source_state (collectors/core/store.py) wrote before 0116 on a read that was not complete.
update source set health = 'unknown', consecutive_failures = 0,
       last_ok_at = case when false then now() else last_ok_at end,
       last_item_at = greatest(last_item_at, null)
 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 0, 'an update of a source that changes nothing is not logged');

-- The same on any other audited table: an ingredient saved unchanged, then changed.
insert into ingredient (id, inn_en) values ('00000000-0000-0000-0000-000000116a01', 'CI auditoxicam');
update ingredient set inn_en = inn_en where id = '00000000-0000-0000-0000-000000116a01';
select pg_temp.as_assert(not exists (select 1 from audit_log where table_name = 'ingredient' and action = 'UPDATE'
                                        and row_pk = '00000000-0000-0000-0000-000000116a01'),
  'an update of an ingredient that changes nothing is not logged');
update ingredient set inn_en = 'CI auditoxicam sodium' where id = '00000000-0000-0000-0000-000000116a01';
select pg_temp.as_assert((select count(*) from audit_log where table_name = 'ingredient' and action = 'UPDATE'
                            and row_pk = '00000000-0000-0000-0000-000000116a01'
                            and old_row ->> 'inn_en' = 'CI auditoxicam'
                            and new_row ->> 'inn_en' = 'CI auditoxicam sodium') = 1,
  'a real change of an ingredient is logged with the old and new row');

-- ───────────── the collector's own status: not logged ─────────────
-- A good read: the last good read and the newest item move.
update source set last_ok_at = now(), last_item_at = now() - interval '1 day' where id = 'ci-as-feed';
-- Failed reads counted while the health stays the same.
update source set consecutive_failures = 1 where id = 'ci-as-feed';
update source set consecutive_failures = 2 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 0,
  'last_ok_at, consecutive_failures and last_item_at alone are not logged: source_run holds every read');

-- ───────────── a change to the source itself: logged, with the whole row ─────────────
update source set health = 'down', consecutive_failures = 3 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 1
    and exists (select 1 from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = 'UPDATE'
                   and old_row ->> 'health' = 'unknown' and new_row ->> 'health' = 'down'),
  'a health change is logged');

update source set url = 'https://as.example.test/new-feed' where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 2
    and exists (select 1 from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = 'UPDATE'
                   and old_row ->> 'url' = 'https://as.example.test/feed'
                   and new_row ->> 'url' = 'https://as.example.test/new-feed'
                   and new_row ? 'last_ok_at'),
  'changing a source''s address is logged with the whole old and new row');

update source set enabled = false, consecutive_failures = 0 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 3
    and exists (select 1 from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = 'UPDATE'
                   and (old_row ->> 'enabled')::boolean and not (new_row ->> 'enabled')::boolean),
  'turning a source off is logged, even with the collector''s columns in the same update');

delete from source where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('DELETE') = 1, 'removing a source is in the audit log');

-- ───────────── the indexes no query could use ─────────────
select pg_temp.as_assert(to_regclass('public.term_concept_subsets') is null
                     and to_regclass('public.mesh_descriptor_trees') is null
                     and to_regclass('public.term_parent_up') is not null,
  'term_concept_subsets and mesh_descriptor_trees are gone; term_parent_up stays');

-- ───────────── the day's size ─────────────
delete from ops_db_size;
select ops_watchdog() as as_wd \gset
select pg_temp.as_assert((select count(*) = 1 and bool_and(db_bytes > 0 and jsonb_typeof(tables) = 'object'
                                                          and (select count(*) from jsonb_object_keys(tables)) between 1 and 15
                                                          and day = (now() at time zone 'Africa/Cairo')::date)
                            from ops_db_size),
  'the watchdog records the day''s database size and its biggest tables');
select pg_temp.as_assert(ops_record_db_size() = 'already recorded' and (select count(*) from ops_db_size) = 1,
  'the size is recorded once a day, however often the watchdog runs');
select pg_temp.as_assert(not has_function_privilege('authenticated', 'public.ops_record_db_size()', 'execute')
                     and not has_table_privilege('authenticated', 'public.ops_db_size', 'insert')
                     and not has_table_privilege('anon', 'public.ops_db_size', 'select'),
  'nobody writes the size history from the app, and the public key cannot read it');

rollback;
