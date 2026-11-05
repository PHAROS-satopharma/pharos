-- PHAROS — who may read what, honest review decisions, and a test message that really arrived (2026-11-05).
--
-- 1. Review decisions. The web app sends from_status and could send created_at. Two reviewers deciding the
--    same notice at once: the second decision was saved from a status that no longer existed, and the
--    history showed a change that never happened; a hand-made request could also backdate a decision.
--    A BEFORE INSERT trigger now stamps the time itself, locks the notice, and refuses a decision whose
--    from_status is not the notice's current status (SQLSTATE PH409, message prefix STALE_DECISION, which
--    the web recognises), a decision that changes nothing, and a decision back to "new" (the web never
--    offers one).
--
-- 2. Personal data. Every signed-in person could read every person's email address and Telegram chat id,
--    the whole audit log (which copies full person rows), and everyone's notifications and subscriptions.
--    Now: person → your own row, or an admin; audit_log → admins only; notification and subscription →
--    your own rows, or an admin. Names stay visible to every active person through person_directory
--    (id, full_name, role, active — nothing else).
--
-- 3. "Turn real messages on". It unlocked as soon as pg_net QUEUED any admin's test message, before
--    Telegram had answered. Each test now records which admin asked for it, telegram_test_delivered() tells
--    THIS admin whether his own latest test got Telegram's answer HTTP 200 with ok=true, and the database
--    refuses to switch dry run off for an admin whose latest test was not delivered.

-- ───────────────────────────── 1. review decisions ─────────────────────────────
create function review_event_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_current issue_status;
begin
  -- The database's clock, never the browser's.
  new.created_at := now();

  -- Lock the notice so two decisions on it are taken one after the other, each against the true status.
  select status into v_current from issue where id = new.issue_id for update;
  if not found then
    raise exception 'That notice no longer exists.' using errcode = '23503';
  end if;

  if new.to_status = 'new' then
    raise exception 'A decision cannot move a notice back to New.' using errcode = '22023';
  end if;
  if new.from_status is distinct from v_current then
    raise exception 'STALE_DECISION: someone else recorded a decision on this notice a moment ago; it is now %.',
      v_current
      using errcode = 'PH409',
            hint = 'Reload the notice and decide again.';
  end if;
  if new.to_status = new.from_status then
    raise exception 'The notice already has that status.' using errcode = '22023';
  end if;
  return new;
end $$;

create trigger review_event_guard before insert on review_event
  for each row execute function review_event_guard();

-- ───────────────────────────── 2. personal data ─────────────────────────────
-- The read policies were created in a loop in 0001_core.sql as <table>_read.
drop policy if exists person_read on person;
create policy person_read on person for select to authenticated
  using (id = my_person_id() or my_role() = 'admin');

drop policy if exists audit_log_read on audit_log;
create policy audit_log_read on audit_log for select to authenticated
  using (my_role() = 'admin');

drop policy if exists notification_read on notification;
create policy notification_read on notification for select to authenticated
  using (person_id = my_person_id() or my_role() = 'admin');

drop policy if exists subscription_read on subscription;
create policy subscription_read on subscription for select to authenticated
  using (person_id = my_person_id() or my_role() = 'admin');

-- Names only, for everyone who may use the app (review history, "linked by", "confirmed by").
-- Not security_invoker: the view reads person as its owner, past person's row-level security, and its own
-- WHERE decides who sees rows (any active signed-in person; the public key sees none).
create view person_directory with (security_barrier = true) as
  select p.id, p.full_name, p.role, p.active
    from person p
   where my_role() is not null;

revoke all on person_directory from public, anon, authenticated;
grant select on person_directory to authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'grant select on person_directory to service_role';
  end if;
end $$;

-- ───────────────────────────── 3. the admin's test message ─────────────────────────────
alter table ops_alert_log
  add column person_id  uuid references person(id) on delete set null,  -- the admin who asked for a test
  add column tg_status  int,                                           -- Telegram's HTTP status, once read
  add column delivered  boolean;                                       -- Telegram answered 200 with ok=true

create index ops_alert_log_test_person on ops_alert_log (person_id, id desc) where kind = 'test';

-- As in 0005, now also recording who asked. create or replace keeps the owner, grants and revokes.
create or replace function send_telegram_test() returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  v_person uuid := my_person_id();
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
    from person where id = v_person;
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
    insert into ops_alert_log (kind, message, dry_run, sent, error, person_id, delivered)
    values ('test', v_msg, false, false, 'Vault secret TELEGRAM_BOT_TOKEN is missing.', v_person, false);
    return jsonb_build_object('ok', false, 'reason', 'The bot token is not in Vault. Run the Supabase deploy again.');
  end if;

  begin
    execute 'select net.http_post(url := $1, body := $2, headers := $3)'
      into v_req
      using 'https://api.telegram.org/bot' || v_token || '/sendMessage',
            jsonb_build_object('chat_id', v_chat, 'text', v_msg, 'disable_web_page_preview', true),
            '{"Content-Type": "application/json"}'::jsonb;
  exception when others then
    insert into ops_alert_log (kind, message, dry_run, sent, error, person_id, delivered)
    values ('test', v_msg, false, false, sqlerrm, v_person, false);
    return jsonb_build_object('ok', false, 'reason', sqlerrm);
  end;

  insert into ops_alert_log (kind, message, dry_run, sent, request_id, person_id)
  values ('test', v_msg, false, true, v_req, v_person);
  return jsonb_build_object('ok', true, 'request_id', v_req);
end $$;

-- Did the CALLING admin's own latest test message reach Telegram?
--   {state:'none'}                         never sent one (or only before this migration)
--   {state:'pending', at}                  handed to pg_net, Telegram has not answered yet
--   {state:'delivered', at}                Telegram answered HTTP 200 with ok=true
--   {state:'failed', at, reason}           refused, timed out, never sent, or the answer is gone
-- The verdict is written back to ops_alert_log the first time it is read, because pg_net deletes its
-- responses after a few hours. Plain Postgres (CI) has no pg_net: guarded with to_regclass.
create function telegram_test_delivered() returns jsonb
language plpgsql volatile security definer
set search_path = public, extensions
as $$
declare
  v_person  uuid := my_person_id();
  r         record;
  v_status  int;
  v_body    text;
  v_err     text;
  v_timeout boolean;
  v_found   boolean := false;
  v_ok      boolean;
  v_reason  text;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'only an admin can read a test result' using errcode = '42501';
  end if;

  select id, at, sent, request_id, error, delivered into r
    from ops_alert_log
   where kind = 'test' and person_id = v_person
   order by id desc
   limit 1;
  if not found then
    return jsonb_build_object('state', 'none');
  end if;

  if r.delivered is not null then
    return jsonb_build_object('state', case when r.delivered then 'delivered' else 'failed' end,
                              'at', r.at, 'reason', case when not r.delivered then r.error end);
  end if;
  if not r.sent or r.request_id is null then
    return jsonb_build_object('state', 'failed', 'at', r.at, 'reason', coalesce(r.error, 'It was not sent.'));
  end if;

  if to_regclass('net._http_response') is not null then
    execute 'select true, status_code, content, error_msg, timed_out from net._http_response where id = $1'
      into v_found, v_status, v_body, v_err, v_timeout using r.request_id;
  end if;

  if not coalesce(v_found, false) or (v_status is null and v_err is null and v_timeout is not true) then
    if r.at > now() - interval '15 minutes' then
      return jsonb_build_object('state', 'pending', 'at', r.at);
    end if;
    v_ok := false;
    v_reason := 'Telegram''s answer to this test can no longer be read. Send a new test message.';
  else
    begin
      v_ok := v_status = 200 and coalesce((v_body::jsonb ->> 'ok')::boolean, false);
    exception when others then
      v_ok := false;
    end;
    if not v_ok then
      v_reason := coalesce(v_err,
                           case when v_timeout then 'Telegram did not answer in time.' end,
                           nullif(left(coalesce(v_body, ''), 300), ''),
                           format('Telegram answered with status %s.', v_status));
    end if;
  end if;

  update ops_alert_log
     set delivered = v_ok, tg_status = v_status, error = coalesce(error, v_reason)
   where id = r.id;

  return jsonb_build_object('state', case when v_ok then 'delivered' else 'failed' end,
                            'at', r.at, 'reason', v_reason);
end $$;

revoke all on function telegram_test_delivered() from public, anon;
grant execute on function telegram_test_delivered() to authenticated;

-- The switch itself: an admin (signed in through the app) may turn real messages on only after his own
-- latest test was delivered. Maintenance as postgres or the service role has no person and is not stopped.
create function app_setting_real_messages_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_check jsonb;
begin
  -- Nested IFs: SQL does not promise to evaluate AND from left to right, and other keys are not booleans.
  if new.key <> 'telegram_dry_run' or old.key <> 'telegram_dry_run' then
    return new;
  end if;
  if new.value is distinct from 'false'::jsonb or old.value = 'false'::jsonb then
    return new;                                  -- not a switch from dry run to real messages
  end if;
  if my_role() is distinct from 'admin' then
    return new;                                  -- postgres or the service role (row-level security stops the rest)
  end if;
  v_check := telegram_test_delivered();
  if v_check ->> 'state' is distinct from 'delivered' then
    raise exception 'Real messages stay off until Telegram has delivered your own test message (now: %).',
      coalesce(v_check ->> 'reason', v_check ->> 'state')
      using errcode = '42501';
  end if;
  return new;
end $$;

create trigger app_setting_real_messages_guard before update on app_setting
  for each row execute function app_setting_real_messages_guard();
