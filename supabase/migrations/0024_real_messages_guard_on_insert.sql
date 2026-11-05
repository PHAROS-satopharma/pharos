-- PHAROS — the real-messages switch is guarded on insert too (audit, 2026-11-05).
--
-- 0008's guard ran only before UPDATE. Admins may insert, update and delete app_setting, so an admin could
-- delete the telegram_dry_run row and insert it again as false, or rename another row to that key, and
-- real messages went on with no delivered test. A missing row already counts as dry run (collectors/alerts.py
-- is_dry_run, 0014), so deleting it stays allowed; whatever creates or changes the row to false is now
-- checked the same way. Maintenance as postgres or the service role is still not stopped.

create or replace function app_setting_real_messages_guard() returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  v_check jsonb;
begin
  -- Nested IFs: SQL does not promise to evaluate AND from left to right, and other keys are not booleans.
  if new.key <> 'telegram_dry_run' then
    return new;
  end if;
  if new.value is distinct from 'false'::jsonb then
    return new;                                  -- not real messages
  end if;
  if tg_op = 'UPDATE' then
    if old.key = 'telegram_dry_run' then
      if old.value = 'false'::jsonb then
        return new;                              -- already on: not a switch
      end if;
    end if;
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

drop trigger if exists app_setting_real_messages_guard on app_setting;
create trigger app_setting_real_messages_guard before insert or update on app_setting
  for each row execute function app_setting_real_messages_guard();
