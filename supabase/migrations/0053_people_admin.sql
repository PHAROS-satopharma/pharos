-- PHAROS — an administrator who does not manage the people (2026-11-06, the owner's word: Dr Sama "can do all the
-- admin things, she only does not have the People tab").
--
-- Dr Sama Mosaad, the QPPV, has been an administrator since 2026-11-05: she confirms ingredients and their names,
-- sets search profiles, switches sources, signs reports. What she does not do is the People screen: inviting
-- someone, changing a person's role, name or access, and another person's alerts. That stays with the owner.
--
-- person.manages_people: true for every person as before (it only matters for an administrator), false for her.
-- i_manage_people(): an active administrator who manages the people. The person and subscription write policies
-- (person_admin, subscription_admin, made in a loop in 0001) now ask for it instead of the administrator role,
-- so the database refuses those writes for her even outside the screen; invite-person asks for it too. Reading is
-- unchanged (an administrator still reads every person, for the names on every screen), and her own alerts stay
-- hers (subscription_self, 0001). The column itself is one of the person row's columns, so only someone who
-- manages the people can change it. Every change to person is in audit_log (0001).

alter table person add column manages_people boolean not null default true;

comment on column person.manages_people is
  'An administrator with false here has every administrator right except the People screen (0053).';

update person set manages_people = false where lower(email) = 'sama.mosaad@satopharma.com';

-- As 0033 and 0045, she is found by her address. On a database that has people (the live one) and not her, the
-- deploy stops here rather than leave her the People screen without a word. A new database (CI) has no people yet.
do $$
begin
  if exists (select 1 from person)
     and not exists (select 1 from person where lower(email) = 'sama.mosaad@satopharma.com' and not manages_people) then
    raise exception 'sama.mosaad@satopharma.com is not on this database: nobody was kept from the People screen.';
  end if;
end $$;

create function i_manage_people() returns boolean language sql stable security definer
set search_path = public as $$
  select coalesce((select manages_people from person
                    where auth_user_id = auth.uid() and active and role = 'admin'), false)
$$;

revoke all on function i_manage_people() from public, anon;
grant execute on function i_manage_people() to authenticated, service_role;

drop policy if exists person_admin on person;
create policy person_admin on person for all to authenticated
  using (i_manage_people()) with check (i_manage_people());

drop policy if exists subscription_admin on subscription;
create policy subscription_admin on subscription for all to authenticated
  using (i_manage_people()) with check (i_manage_people());
