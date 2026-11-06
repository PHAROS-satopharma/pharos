-- PHAROS — "Mark as looked at" stamps the time the list on screen was read, not the time of the click
-- (2026-11-06, finding 7 of the review of #103).
--
-- The Sources page reads what the authorities published once, when it opens. mark_country_looked() stamped
-- now(): a notice that arrived while the card stayed open (a collector run every 4 hours) was never on the
-- screen, yet fell before the new look and never showed as new. The page now sends the time it read its
-- list (p_seen_to); the look is that time, never later than now(). Without it the look is now(), as before.

drop function mark_country_looked(text);

create function mark_country_looked(p_regulator text, p_seen_to timestamptz default null) returns timestamptz
language plpgsql security definer set search_path = public as $$
declare
  v_person  uuid := my_person_id();
  v_country text;
  v_at      timestamptz := least(coalesce(p_seen_to, now()), now());
begin
  if v_person is null then
    raise exception 'Only a member of the team can mark a country as looked at.' using errcode = '42501';
  end if;
  select country_name into v_country from regulator where id = p_regulator;
  if v_country is null then
    raise exception 'Unknown authority: %', p_regulator using errcode = '22023';
  end if;
  insert into country_look (person_id, regulator_id, looked_at)
  select v_person, r.id, v_at from regulator r where r.country_name = v_country;
  return v_at;
end $$;
revoke all on function mark_country_looked(text, timestamptz) from public, anon;
grant execute on function mark_country_looked(text, timestamptz) to authenticated;
