-- PHAROS — the admin's test message, the step before real Telegram messages are turned on.
-- The admin presses "Send me a test message" on My account: one real message goes to HIS OWN linked chat
-- (never to anyone else), whatever app_setting.telegram_dry_run says. He reads it, then turns real
-- messages on himself (an admin write to app_setting, recorded in audit_log by its trigger).
-- The bot token is read from Vault (copied there by deploy-supabase.yml). Plain Postgres (CI) has no
-- Vault or pg_net: the function answers with the reason instead of failing.

create function send_telegram_test() returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  v_chat   bigint;
  v_name   text;
  v_token  text;
  v_msg    text;
  v_req    bigint;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'only an admin can send a test message' using errcode = '42501';
  end if;

  select telegram_chat_id, full_name into v_chat, v_name
    from person where id = my_person_id();
  if v_chat is null then
    return jsonb_build_object('ok', false, 'reason', 'Your Telegram is not connected yet.');
  end if;

  v_msg := 'PHAROS: test message' || E'\n\n'
        || 'Sent at ' || to_char(now() at time zone 'Africa/Cairo', 'DD Mon YYYY HH24:MI') || ' Cairo time, at the '
        || 'request of ' || v_name || '.' || E'\n'
        || 'Safety notices will arrive in this chat as soon as they are found, each with the country, the '
        || 'regulator, the notice title as published and its link.';

  begin
    execute 'select decrypted_secret from vault.decrypted_secrets where name = $1 limit 1'
      into v_token using 'TELEGRAM_BOT_TOKEN';
  exception when others then
    v_token := null;
  end;
  if v_token is null then
    insert into ops_alert_log (kind, message, dry_run, sent, error)
    values ('test', v_msg, false, false, 'Vault secret TELEGRAM_BOT_TOKEN is missing.');
    return jsonb_build_object('ok', false, 'reason', 'The bot token is not in Vault. Run the Supabase deploy again.');
  end if;

  begin
    execute 'select net.http_post(url := $1, body := $2, headers := $3)'
      into v_req
      using 'https://api.telegram.org/bot' || v_token || '/sendMessage',
            jsonb_build_object('chat_id', v_chat, 'text', v_msg, 'disable_web_page_preview', true),
            '{"Content-Type": "application/json"}'::jsonb;
  exception when others then
    insert into ops_alert_log (kind, message, dry_run, sent, error) values ('test', v_msg, false, false, sqlerrm);
    return jsonb_build_object('ok', false, 'reason', sqlerrm);
  end;

  insert into ops_alert_log (kind, message, dry_run, sent, request_id) values ('test', v_msg, false, true, v_req);
  return jsonb_build_object('ok', true, 'request_id', v_req);
end $$;

-- What Telegram answered to a test message: {done:false} while pg_net is still waiting, then
-- {done:true, ok, status, reason}. Only for requests that send_telegram_test made.
create function telegram_test_result(p_request_id bigint) returns jsonb
language plpgsql stable security definer
set search_path = public, extensions
as $$
declare
  v_status  int;
  v_body    text;
  v_err     text;
  v_timeout boolean;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'only an admin can read a test result' using errcode = '42501';
  end if;
  if not exists (select 1 from ops_alert_log where kind = 'test' and request_id = p_request_id) then
    raise exception 'no such test message';
  end if;

  begin
    execute 'select status_code, content, error_msg, timed_out from net._http_response where id = $1'
      into v_status, v_body, v_err, v_timeout using p_request_id;
  exception when others then
    return jsonb_build_object('done', true, 'ok', false, 'reason', sqlerrm);
  end;

  if v_status is null and v_err is null and v_timeout is not true then
    return jsonb_build_object('done', false);
  end if;
  return jsonb_build_object(
    'done', true,
    'ok', v_status = 200,
    'status', v_status,
    'reason', coalesce(v_err,
                       case when v_timeout then 'Telegram did not answer in time.' end,
                       case when v_status <> 200 then left(v_body, 300) end));
end $$;

revoke all on function send_telegram_test(), telegram_test_result(bigint) from public, anon;
grant execute on function send_telegram_test(), telegram_test_result(bigint) to authenticated;
