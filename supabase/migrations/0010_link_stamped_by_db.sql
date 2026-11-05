-- PHAROS — a manual link between notices is recorded as the person who made it, at the database's time
-- (2026-11-05).
--
-- issue_document_write let a reviewer or admin insert or update a link with any linked_by and any
-- linked_at: the web app sends both, so the audit trail of a merge could name someone else, or a time the
-- browser chose. Now every link a signed-in person writes is stamped here with that person and now().
-- The collectors (service role, no signed-in user) keep writing their automatic links as before.

create function issue_document_stamp() returns trigger
language plpgsql security definer
set search_path = public as $$
begin
  if auth.uid() is not null then
    new.linked_by := my_person_id();
    new.linked_at := now();
  end if;
  return new;
end $$;

revoke all on function issue_document_stamp() from public, anon, authenticated;

create trigger issue_document_stamp before insert or update on issue_document
  for each row execute function issue_document_stamp();
