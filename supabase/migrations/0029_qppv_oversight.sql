-- PHAROS — the QPPV's oversight page and the morning escalation (2026-11-05).
--
-- overdue_items(day) lists what is late on that Cairo day: a signal past the due date of its stage, and a
-- notice still "new" more than review_due_days (app_setting, 7 by default) after PHAROS found it. It also
-- lists, as "psur", each EURD data lock point or submission date of a watched ingredient in the next 90
-- days (days_late is then negative: the days left). The function is security invoker: a signed-in person
-- sees what their own reading rights show, and the collectors (as the database owner) see everything.
--
-- collectors/escalate.py sends the late signals and notices to every administrator on Telegram once a
-- Cairo day, as notification kind 'escalation'; it honours telegram_dry_run like every other message.

alter type notif_kind add value if not exists 'escalation';

insert into app_setting (key, value) values ('review_due_days', '7') on conflict (key) do nothing;

create function overdue_items(p_day date default signal_cairo_today())
returns table (kind text, ref_id uuid, label text, title text, ingredient text, due date, days_late int)
language sql stable security invoker set search_path = public as $$
  select 'signal', s.id, s.ref, s.title, s.ingredient, s.next_due, (p_day - s.next_due)
    from v_signal_table s
   where s.stage <> 'closed' and s.next_due < p_day
  union all
  select 'review', i.id, null, i.title,
         (select string_agg(ing.inn_en, ', ' order by ing.inn_en)
            from issue_ingredient ii join ingredient ing on ing.id = ii.ingredient_id where ii.issue_id = i.id),
         d.due, (p_day - d.due)
    from issue i
    cross join lateral (
      select ((i.created_at at time zone 'Africa/Cairo')::date
              + coalesce((select (value #>> '{}')::int from app_setting where key = 'review_due_days'), 7)) as due
    ) d
   where i.status = 'new' and not i.is_backfill and d.due < p_day
  union all
  select 'psur', ing.id, e.procedure, x.what || ' · ' || e.substance, ing.inn_en, x.due, (p_day - x.due)
    from eurd_entry e
    join ingredient ing on ing.id = e.ingredient_id
    cross join lateral (values ('PSUR data lock point', e.dlp), ('PSUR submission', e.submission_date)) x(what, due)
   where x.due between p_day and p_day + 90
  order by 1, 7 desc, 6
$$;

revoke all on function overdue_items(date) from public, anon;
grant execute on function overdue_items(date) to authenticated;
