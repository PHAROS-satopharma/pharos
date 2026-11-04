-- PHAROS — operations (owner: platform).
-- Inbound newsletter mail, source probes, Telegram link codes, the "test against archive" count,
-- the pg_cron watchdog, and the weekly archive check. Applies after 0001_core.sql.
--
-- Plain Postgres (CI) has no pg_cron, pg_net or Vault: the watchdog function is still created, but it is
-- scheduled only on Supabase (detected by the vault schema).

-- ───────────────────────────── inbound newsletter mail ─────────────────────────────
-- Written by the Cloudflare Email Worker (service role); read and marked processed by the email_inbox parser.
create table inbound_email (
  id            uuid primary key default gen_random_uuid(),
  source_id     text references source(id),          -- fimea-email / tga-email, by recipient alias
  received_at   timestamptz not null default now(),
  from_addr     text,
  subject       text,
  r2_key        text,                                -- inbound/<date>/<uuid>.eml (the raw message)
  text_body     text,
  html_body     text,
  processed_at  timestamptz
);
create index inbound_email_unprocessed on inbound_email (source_id, received_at) where processed_at is null;
create index inbound_email_received on inbound_email (received_at desc);

-- ───────────────────────────── source probes ("test link") ─────────────────────────────
create table probe_result (
  id                uuid primary key default gen_random_uuid(),
  url               text not null,
  requested_by      uuid references person(id),
  requested_at      timestamptz default now(),
  status            text default 'queued' check (status in ('queued','running','ok','failed')),
  channel_detected  text,
  parser_detected   text,
  items             jsonb,
  error             text,
  finished_at       timestamptz
);
create index probe_result_requested on probe_result (requested_at desc);

-- ───────────────────────────── ops bookkeeping ─────────────────────────────
-- Small key/value state for the watchdog (last alert time). Only definer functions and the service role.
create table ops_state (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- Every admin alert the watchdog raised, sent or not (dry run). Evidence for the monthly report.
create table ops_alert_log (
  id          bigserial primary key,
  at          timestamptz not null default now(),
  kind        text not null,                         -- watchdog
  message     text not null,
  dry_run     boolean not null,
  sent        boolean not null default false,        -- handed to pg_net (reply lands in net._http_response)
  request_id  bigint,                                -- pg_net request id
  error       text
);

-- Weekly archive integrity check (db-backup.yml, job verify-archive): sampled objects re-hashed against
-- the sha256 stored in the database.
create table archive_check (
  id          bigserial primary key,
  checked_at  timestamptz not null default now(),
  sampled     int not null,
  mismatched  int not null,
  missing     int not null,
  details     jsonb,                                 -- [{r2_key, expected, actual}] for failures only
  git_sha     text
);

-- ───────────────────────────── row-level security ─────────────────────────────
alter table inbound_email  enable row level security;
alter table probe_result   enable row level security;
alter table ops_state      enable row level security;
alter table ops_alert_log  enable row level security;
alter table archive_check  enable row level security;

create policy inbound_email_read on inbound_email for select to authenticated using (my_role() is not null);
create policy probe_result_read  on probe_result  for select to authenticated using (my_role() is not null);
create policy archive_check_read on archive_check for select to authenticated using (my_role() is not null);
create policy ops_alert_log_read on ops_alert_log for select to authenticated using (my_role() = 'admin');

-- An admin queues a probe as themselves (the probe-source function inserts with the admin's session, so the
-- audit is truthful). Everything after 'queued' is written by the probe workflow with the service role.
create policy probe_result_admin_insert on probe_result for insert to authenticated
  with check (my_role() = 'admin' and requested_by = my_person_id() and coalesce(status, 'queued') = 'queued');

-- Table privileges: the public key gets nothing; signed-in people only what the policies allow.
revoke all on inbound_email, probe_result, ops_state, ops_alert_log, archive_check from anon;
revoke all on ops_state from authenticated;
revoke insert, update, delete, truncate on inbound_email, ops_alert_log, archive_check from authenticated;
revoke update, delete, truncate on probe_result from authenticated;
grant select on inbound_email, probe_result, ops_alert_log, archive_check to authenticated;
grant insert on probe_result to authenticated;
revoke all on sequence ops_alert_log_id_seq, archive_check_id_seq from anon, authenticated;

-- ───────────────────────────── RPC: Telegram link code ─────────────────────────────
-- Returns a one-time 24-character URL-safe code for the caller; only its sha256 is stored. The web app
-- builds https://t.me/<TELEGRAM_BOT_USERNAME>?start=<code>; telegram-webhook consumes it.
-- Creating a new code retires the caller's older unused codes (kept, expired, for the record).
create function create_link_token() returns text
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  v_person uuid := my_person_id();
  v_code   text;
begin
  if v_person is null then
    raise exception 'Only a signed-in, active person can create a Telegram link code.'
      using errcode = '42501';
  end if;

  update link_token set expires_at = now()
   where person_id = v_person and used_at is null and expires_at > now();

  -- 18 random bytes → exactly 24 base64 characters, made URL-safe (Telegram /start allows A-Z a-z 0-9 _ -).
  v_code := translate(encode(gen_random_bytes(18), 'base64'), '+/', '-_');

  insert into link_token (token_hash, person_id, expires_at)
  values (encode(sha256(convert_to(v_code, 'UTF8')), 'hex'), v_person, now() + interval '24 hours');

  return v_code;
end $$;

-- ───────────────────────────── RPC: test a term against the archive ─────────────────────────────
-- How many stored texts (document_text rows) contain p_term, case-insensitively, optionally only those whose
-- document language is p_lang (or a sub-tag of it, e.g. 'de' also counts 'de-CH').
--
-- Work cap: a SET statement_timeout inside a function does not arm for the statement already running, so
-- the loop itself stops after 4 seconds (SQLSTATE 57014) or at 10,000 hits (returned as 10000 = "at least").
-- The outer hard cap is the authenticated role's statement timeout that PostgREST applies (8 s on Supabase).
create function archive_hit_count(p_term text, p_lang text default null) returns int
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  v_term     text := btrim(coalesce(p_term, ''));
  v_lang     text := nullif(lower(btrim(coalesce(p_lang, ''))), '');
  v_pattern  text;
  v_count    int := 0;
  v_rows     int := 0;
  v_started  timestamptz := clock_timestamp();
  r          record;
begin
  if my_role() is null then
    raise exception 'Sign in to test a term against the archive.' using errcode = '42501';
  end if;
  if char_length(v_term) < 2 or char_length(v_term) > 200 then
    raise exception 'The term must be 2 to 200 characters long.' using errcode = '22023';
  end if;

  -- The term is literal text: escape the LIKE wildcards.
  v_pattern := '%' || replace(replace(replace(v_term, '\', '\\'), '%', '\%'), '_', '\_') || '%';

  for r in
    select dt.text
      from document_text dt
      join document d on d.id = dt.document_id
     where v_lang is null
        or lower(d.lang) = v_lang
        or lower(d.lang) like v_lang || '-%'
  loop
    v_rows := v_rows + 1;
    if r.text ilike v_pattern then
      v_count := v_count + 1;
      exit when v_count >= 10000;
    end if;
    if v_rows % 25 = 0 and clock_timestamp() - v_started > interval '4 seconds' then
      raise exception 'The archive test took too long. Try a longer term or pick one language.'
        using errcode = '57014';
    end if;
  end loop;

  return v_count;
end $$;

-- ───────────────────────────── watchdog ─────────────────────────────
-- Every 30 minutes (pg_cron): if no collector run has finished in the last 6 hours, or the database is
-- larger than 350 MB, tell the admin on Telegram — at most once every 6 hours. While
-- app_setting.telegram_dry_run is true (the default) the alert is only logged in ops_alert_log.
-- The bot token and the admin chat id are read from Supabase Vault (TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_CHAT_ID);
-- without ADMIN_TELEGRAM_CHAT_ID it uses the linked Telegram chat of the first active admin.
create function ops_watchdog() returns text
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
  select max(finished_at) into v_last_run from run where finished_at is not null;

  if v_last_run is null then
    v_problems := v_problems || 'No collector run has finished yet.'::text;
  elsif v_last_run < now() - interval '6 hours' then
    v_problems := v_problems || format(
      'No collector run has finished for %s hours. The last one finished %s (Cairo time).',
      floor(extract(epoch from now() - v_last_run) / 3600)::int,
      to_char(v_last_run at time zone 'Africa/Cairo', 'DD Mon YYYY HH24:MI'));
  end if;

  if v_db_bytes > 350::bigint * 1024 * 1024 then
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

  select (value #>> '{}')::boolean into v_dry from app_setting where key = 'telegram_dry_run';
  v_dry := coalesce(v_dry, true);

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

  -- No admin chat id in Vault: fall back to the linked Telegram chat of the first active admin.
  if v_chat is null then
    select telegram_chat_id::text into v_chat
      from person
     where role = 'admin' and active and telegram_chat_id is not null
     order by created_at
     limit 1;
  end if;

  if v_token is null or v_chat is null then
    insert into ops_alert_log (kind, message, dry_run, sent, error)
    values ('watchdog', v_msg, false, false, 'Vault secret TELEGRAM_BOT_TOKEN is missing, or no admin chat (Vault ADMIN_TELEGRAM_CHAT_ID or a linked admin).');
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

-- Used only by deploy-supabase.yml (connected as postgres) to copy GitHub secrets into Vault, so the owner
-- pastes each secret in one place. Not callable through the API.
create function ops_set_vault_secret(p_name text, p_value text) returns void
language plpgsql volatile
set search_path = public
as $$
declare
  v_id uuid;
begin
  if coalesce(p_value, '') = '' then
    return;                                            -- an unset GitHub secret never blanks a Vault entry
  end if;
  execute 'select id from vault.secrets where name = $1 limit 1' into v_id using p_name;
  if v_id is null then
    execute 'select vault.create_secret($1, $2)' using p_value, p_name;
  else
    execute 'select vault.update_secret($1, $2)' using v_id, p_value;
  end if;
end $$;

-- ───────────────────────────── function privileges ─────────────────────────────
revoke all on function create_link_token()                from public, anon;
revoke all on function archive_hit_count(text, text)      from public, anon;
revoke all on function ops_watchdog()                     from public, anon, authenticated;
revoke all on function ops_set_vault_secret(text, text)   from public, anon, authenticated;
grant execute on function create_link_token()           to authenticated;
grant execute on function archive_hit_count(text, text) to authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke all on function ops_set_vault_secret(text, text) from service_role';
    execute 'grant execute on function ops_watchdog() to service_role';
  end if;
end $$;

-- ───────────────────────────── schedule (Supabase only) ─────────────────────────────
do $do$
begin
  if not exists (select 1 from pg_namespace where nspname = 'vault') then
    raise notice 'Not Supabase (no vault schema): the watchdog is created but not scheduled.';
    return;
  end if;

  if not exists (select 1 from pg_extension where extname = 'pg_net') then
    execute 'create extension pg_net with schema extensions';
  end if;
  if not exists (select 1 from pg_extension where extname = 'pg_cron') then
    execute 'create extension pg_cron with schema pg_catalog';
  end if;

  -- Re-scheduling by name replaces the job, so re-running this file is harmless.
  perform cron.schedule('pharos-watchdog', '*/30 * * * *', 'select public.ops_watchdog()');
end $do$;
