-- Dr Sama edits her own sources (her feedback, 8 Nov 2026): on Sources she adds, changes and removes the links
-- she checks (regulator_page) and adds local references — an authority with its first link.
--
-- What already holds and is not changed here: regulator_page is written by admins only and every change is in
-- the audit log (0032); regulator is written by admins only (0004).
--
-- New here: a change to the authorities themselves is in the audit log too. Until now regulator had no audit
-- trigger. The collector re-writes every catalogue authority on each run (Store.upsert_regulator), so an update
-- is logged only when it changes something; adding or removing an authority is always logged.

create trigger audit_regulator_write after insert or delete on regulator
  for each row execute function audit_row();
create trigger audit_regulator_change after update on regulator
  for each row when (old.* is distinct from new.*) execute function audit_row();
