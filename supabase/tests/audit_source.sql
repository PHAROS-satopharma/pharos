-- PHAROS CI — a source is in the audit log when something about it changes, not each time the collector reads it
-- (0116). Everything happens in one transaction that is rolled back at the end.

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

-- ───────────── what the collector writes after each read: not in the audit log ─────────────
-- Store.set_source_state (collectors/core/store.py) on a run that was not complete: nothing changes.
update source set health = 'unknown', consecutive_failures = 0,
       last_ok_at = case when false then now() else last_ok_at end,
       last_item_at = greatest(last_item_at, null)
 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 0, 'an update that changes nothing is not logged');

-- A good read: health, the failure count, the last good read and the newest item move.
update source set health = 'ok', consecutive_failures = 0, last_ok_at = now(),
       last_item_at = greatest(last_item_at, now() - interval '1 day')
 where id = 'ci-as-feed';
-- A failed read, then another.
update source set health = 'degraded', consecutive_failures = 1 where id = 'ci-as-feed';
update source set health = 'down', consecutive_failures = 3 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 0,
  'the collector''s own state (health, failures, last good read, newest item) is not logged: source_run holds every read');

-- ───────────── a change to the source itself: logged, with the whole row ─────────────
update source set url = 'https://as.example.test/new-feed' where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 1
    and exists (select 1 from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = 'UPDATE'
                   and old_row ->> 'url' = 'https://as.example.test/feed'
                   and new_row ->> 'url' = 'https://as.example.test/new-feed'
                   and new_row ? 'last_ok_at'),
  'changing a source''s address is logged with the old and new row');

-- Turned off in the same statement as a state change: logged.
update source set enabled = false, health = 'unknown', consecutive_failures = 0 where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('UPDATE') = 2
    and exists (select 1 from audit_log where table_name = 'source' and row_pk = 'ci-as-feed' and action = 'UPDATE'
                   and (old_row ->> 'enabled')::boolean and not (new_row ->> 'enabled')::boolean),
  'turning a source off is logged, even with the collector''s columns in the same update');

delete from source where id = 'ci-as-feed';
select pg_temp.as_assert(pg_temp.as_count('DELETE') = 1, 'removing a source is in the audit log');

-- ───────────── the index nothing searched by ─────────────
select pg_temp.as_assert(to_regclass('public.term_concept_subsets') is null, 'term_concept_subsets is gone');

rollback;
