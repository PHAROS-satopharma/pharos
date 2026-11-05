-- PHAROS — the watchdog reads the dry-run switch the way everything else does (audit, 2026-11-05).
--
-- The collector (collectors/alerts.py is_dry_run) and the switch guard (0008) treat telegram_dry_run as
-- OFF only when it is exactly the JSON boolean false. The watchdog cast the value to boolean instead, so
-- the text "false", "off", "no" or 0 sent real admin alerts while every other part stayed in dry run, and
-- any other text (for example "maybe") made the cast fail and the watchdog stop with an error.
-- It now goes live only on the JSON boolean false; anything else, or no row, stays in dry run.
--
-- Only the dry-run read changes; the rest of the function is 0006's. create or replace keeps its owner,
-- grants and revokes.

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
