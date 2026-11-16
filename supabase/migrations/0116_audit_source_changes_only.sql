-- PHAROS — the database stops growing by audit rows that record no change (17 Nov 2026).
--
-- Why: the database grew from 338 MB on 10 Nov to 374 MB on 17 Nov, about 5 MB a day, towards the terminology
-- loader's 400 MB (collectors/coding/terminology/base.py MAX_DB_BYTES) and the watchdog's 420 MB (0104). The only
-- steady daily growth was the audit log: after every source it reads, the collector writes that source's state
-- (Store.set_source_state: health, consecutive_failures, last_ok_at, last_item_at), and audit_source (0001) copied
-- the whole row, before and after, every time. From 10 to 17 Nov that was 7,972 rows that changed nothing (11 MB)
-- and 1,871 that changed only the collector's own status (2.7 MB). Every read is already in source_run (each run,
-- each source, HTTP status, counts, error), which is what the watchdog and the Sources screen read.
--
-- 1. audit_row() logs no UPDATE whose old and new rows are the same, on every audited table. Inserts, deletes and
--    every update that changes something are logged exactly as before.
-- 2. source, as 0098 does for regulator: adding or removing a source is always logged; an update is logged when it
--    changes anything other than last_ok_at, consecutive_failures and last_item_at. A health change, turning a
--    source on or off and every edit of a source (its address, schedule, filters) are logged, with the whole old
--    and new row.
-- 3. Two indexes no query can use, dropped: term_concept_subsets (0103; nothing filters on subsets, they are only
--    shown) and mesh_descriptor_trees (0061; the queries read trees one by one, with = any, unnest and like, which a
--    GIN index on the array cannot serve). Both had 0 scans on 17 Nov. term_parent_up stays: the child count (0105)
--    reads it.
-- 4. ops_db_size: once a day, the database's size and its 15 biggest tables, written by the watchdog's own timer
--    (pharos-watchdog, every 30 minutes, 0002). Until now the size was read only when someone asked, so a rise
--    could not be traced to a table.
--
-- The rows already written stay: the audit log is append-only (0046). The database stops growing by them; it does
-- not shrink. collectors/core/store.py set_source_state now writes only when a value changes, so a read that
-- changes nothing leaves no dead row either.

-- ───────────────────────────── 1. no audit row for an update that changes nothing ─────────────────────────────
-- Same body as 0001, plus the first line. create or replace keeps its owner and every trigger that uses it.
create or replace function audit_row() returns trigger language plpgsql security definer
set search_path = public as $$
begin
  if tg_op = 'UPDATE' and to_jsonb(old) = to_jsonb(new) then
    return new;
  end if;
  insert into audit_log (table_name, row_pk, action, old_row, new_row, actor)
  values (tg_table_name,
          coalesce((to_jsonb(new)->>'id'), (to_jsonb(old)->>'id'), (to_jsonb(new)->>'issue_id')),
          tg_op,
          case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end,
          case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end,
          auth.uid());
  return coalesce(new, old);
end $$;

-- ───────────────────────────── 2. a source: logged when the source itself changes ─────────────────────────────
drop trigger audit_source on source;

create trigger audit_source_write after insert or delete on source
  for each row execute function audit_row();
create trigger audit_source_change after update on source
  for each row
  when ((to_jsonb(old) - array['last_ok_at', 'consecutive_failures', 'last_item_at'])
        is distinct from
        (to_jsonb(new) - array['last_ok_at', 'consecutive_failures', 'last_item_at']))
  execute function audit_row();

-- ───────────────────────────── 3. indexes no query can use ─────────────────────────────
drop index if exists term_concept_subsets;
drop index if exists mesh_descriptor_trees;

-- ───────────────────────────── 4. the size, once a day ─────────────────────────────
create table ops_db_size (
  day       date primary key,                     -- Cairo date
  at        timestamptz not null default now(),
  db_bytes  bigint not null,
  tables    jsonb not null                        -- {"schema.table": total bytes}, the 15 biggest
);
alter table ops_db_size enable row level security;
create policy ops_db_size_read on ops_db_size for select to authenticated using (my_role() = 'admin');
revoke all on ops_db_size from anon;
revoke insert, update, delete, truncate on ops_db_size from authenticated;
grant select on ops_db_size to authenticated;

create function ops_record_db_size() returns text
language plpgsql volatile security definer
set search_path = public
as $$
declare
  v_day date := (now() at time zone 'Africa/Cairo')::date;
begin
  if exists (select 1 from ops_db_size where day = v_day) then
    return 'already recorded';
  end if;
  insert into ops_db_size (day, db_bytes, tables)
  select v_day, pg_database_size(current_database()),
         coalesce((select jsonb_object_agg(name, bytes)
                     from (select n.nspname || '.' || c.relname as name, pg_total_relation_size(c.oid) as bytes
                             from pg_class c join pg_namespace n on n.oid = c.relnamespace
                            where c.relkind in ('r', 'm', 'p')
                              and n.nspname not in ('pg_catalog', 'information_schema')
                            order by pg_total_relation_size(c.oid) desc
                            limit 15) t), '{}'::jsonb)
  on conflict (day) do nothing;
  return 'recorded';
end $$;
revoke all on function ops_record_db_size() from public, anon, authenticated;

-- The watchdog records the day's size first; the rest of ops_watchdog is 0104's.
-- create or replace keeps its owner, grants and revokes.
create or replace function ops_watchdog() returns text
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  v_last_run    timestamptz;
  v_db_bytes    bigint := pg_database_size(current_database());
  v_problems    text[] := '{}';
  v_last_alert  timestamptz;
  v_dry         boolean;
  v_token       text;
  v_chat        text;
  v_msg         text;
  v_req         bigint;
begin
  -- The day's size (0116). A failure here never stops the watchdog.
  begin
    perform ops_record_db_size();
  exception when others then
    null;
  end;

  -- A run that merely FINISHED proves nothing: it may have crashed, or every source may have failed.
  -- last_ok_at is set only when a source was read completely without an error.
  select max(last_ok_at) into v_last_run from source where enabled;

  if v_last_run is null then
    v_problems := v_problems || 'No collector run has checked a source successfully yet.'::text;
  elsif v_last_run < now() - interval '6 hours' then
    v_problems := v_problems || format(
      'No collector run has checked a source successfully for %s hours. The last good check was %s (Cairo time).',
      floor(extract(epoch from now() - v_last_run) / 3600)::int,
      to_char(v_last_run at time zone 'Africa/Cairo', 'DD Mon YYYY HH24:MI'));
  end if;

  if v_db_bytes > 420::bigint * 1024 * 1024 then
    v_problems := v_problems || format(
      'The database is %s MB. The free plan stops writing at 500 MB.',
      round(v_db_bytes / 1048576.0));
  end if;

  if cardinality(v_problems) = 0 then
    return 'ok';
  end if;

  select (value #>> '{}')::timestamptz into v_last_alert
    from ops_state where key = 'watchdog_last_alert_at';
  if v_last_alert is not null and v_last_alert > now() - interval '6 hours' then
    return 'suppressed';
  end if;

  v_msg := 'PHAROS: admin alert' || E'\n\n' || array_to_string(v_problems, E'\n');

  -- Real messages only on exactly the JSON boolean false, as in the collector and the switch guard.
  v_dry := not exists (select 1 from app_setting
                        where key = 'telegram_dry_run' and value = 'false'::jsonb);

  insert into ops_state (key, value, updated_at)
  values ('watchdog_last_alert_at', to_jsonb(now()), now())
  on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;

  if v_dry then
    insert into ops_alert_log (kind, message, dry_run, sent) values ('watchdog', v_msg, true, false);
    insert into notification (person_id, kind, dry_run, summary) values (null, 'health', true, v_msg);
    return 'logged (dry run)';
  end if;

  begin
    execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
      into v_token using 'TELEGRAM_BOT_TOKEN';
    execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
      into v_chat using 'ADMIN_TELEGRAM_CHAT_ID';
  exception when others then
    v_token := null;
  end;

  -- No admin chat id in Vault: fall back to the first admin who asked for source health alerts.
  if v_chat is null then
    v_chat := ops_health_chat();
  end if;

  if v_token is null or v_chat is null then
    insert into ops_alert_log (kind, message, dry_run, sent, error)
    values ('watchdog', v_msg, false, false, 'Vault secret TELEGRAM_BOT_TOKEN is missing, or no admin chat (Vault ADMIN_TELEGRAM_CHAT_ID or a linked admin with Source health alerts).');
    return 'not sent: Vault secrets missing';
  end if;

  begin
    execute 'select net.http_post(url := $1, body := $2, headers := $3)'
      into v_req
      using 'https://api.telegram.org/bot' || v_token || '/sendMessage',
            jsonb_build_object('chat_id', v_chat, 'text', v_msg, 'disable_web_page_preview', true),
            '{"Content-Type": "application/json"}'::jsonb;
  exception when others then
    insert into ops_alert_log (kind, message, dry_run, sent, error)
    values ('watchdog', v_msg, false, false, sqlerrm);
    return 'not sent: ' || sqlerrm;
  end;

  insert into ops_alert_log (kind, message, dry_run, sent, request_id)
  values ('watchdog', v_msg, false, true, v_req);
  insert into notification (person_id, kind, dry_run, summary) values (null, 'health', false, v_msg);
  return 'sent';
end $$;
