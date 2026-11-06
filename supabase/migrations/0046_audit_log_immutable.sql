-- PHAROS — inspection evidence, part 1 (2026-11-06, the QPPV plan, phase 14).
--
-- The weekly report goes into Dr Sama's SOP and the pharmacovigilance system master file, so what the app
-- recorded must stand up to an inspection.
--
-- 1. audit_log is append-only. Every audited table writes its old and new rows here (audit_row(), 0001); until
--    now the database owner, the service key and any role holding the table rights could change or empty it.
--    A row trigger now refuses every UPDATE and DELETE and a statement trigger every TRUNCATE, for every role,
--    the owner included (as sign_off, 0030), and the rights to do so are revoked from every API role.
--    Nothing in PHAROS ever changed or removed an audit row (no retention job, no collector, no migration);
--    inserts by audit_row() are untouched.
-- 2. sign_kind gains 'weekly_report' and 'pack', so the weekly report (and, from the next phase, a PSUR or
--    inspection pack) can be signed. Postgres refuses a new enum value in the transaction that added it, so
--    every use of these values is in 0047.

-- ───────────────────────────── 1. the audit log is never changed ─────────────────────────────
create function audit_log_immutable() returns trigger language plpgsql set search_path = public as $$
begin
  raise exception 'The audit log is never changed or removed.' using errcode = '42501';
end $$;
revoke all on function audit_log_immutable() from public, anon, authenticated;

create trigger audit_log_no_change before update or delete on audit_log
  for each row execute function audit_log_immutable();
create trigger audit_log_no_truncate before truncate on audit_log
  for each statement execute function audit_log_immutable();

revoke update, delete, truncate on audit_log from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    execute 'revoke update, delete, truncate on audit_log from service_role';
    execute 'revoke all on function audit_log_immutable() from service_role';
  end if;
end $$;

comment on table audit_log is
  'Every insert, update and delete on the audited tables, with the old and new rows. Append-only: an update, delete or truncate is refused for every role, the owner included (0046).';

-- ───────────────────────────── 2. what can be signed ─────────────────────────────
alter type sign_kind add value if not exists 'weekly_report';
alter type sign_kind add value if not exists 'pack';
