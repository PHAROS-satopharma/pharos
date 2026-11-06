-- PHAROS — a signature is never emptied, and the service key never writes one (2026-11-06, audit finding 12).
--
-- sign_off has been append-only since 0030: a row trigger refuses every update and delete. A row trigger does
-- not fire on TRUNCATE, so the whole table could still be emptied in one statement, and 0030 revoked the write
-- rights from anon and authenticated only: service_role kept insert, update, delete and truncate through the
-- schema's default grants, so the service key could add a signature sign_record() never checked.
--
-- 1. A statement trigger refuses every TRUNCATE, for every role, the owner included (as audit_log, 0046).
-- 2. service_role loses insert, update, delete and truncate; it keeps select (report_pack.py reads signatures).
--    A signature is written only by sign_record() (security definer), so nothing in
--    PHAROS loses a right it used.

create trigger sign_off_no_truncate before truncate on sign_off
  for each statement execute function sign_off_immutable();

revoke all on function sign_off_immutable() from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke insert, update, delete, truncate on sign_off from service_role';
    execute 'revoke all on function sign_off_immutable() from service_role';
  end if;
end $$;

comment on table sign_off is
  'Electronic signatures. Append-only: an update, delete or truncate is refused for every role, the owner included (0030, 0060); only sign_record() writes a row.';
