-- PHAROS CI — Dr Sama edits her own sources (0098, her feedback of 8 Nov 2026). Runs on the database ci.yml
-- prepared: CI Admin (…a1) and CI Reader (…b2) exist.

create function pg_temp.se_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

-- A catalogue authority, as the collector writes it.
insert into regulator (id, country_code, country_name, name, languages, homepage)
  values ('CI-SE-CAT', 'SA', 'CI Saudi Arabia', 'CI Food and Drug Authority', '{ar,en}', 'https://sfda.example.test/');

-- ───────────── as an admin: a local reference, then her links on it ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', false);
set role authenticated;
insert into regulator (id, country_code, country_name, name, languages)
  values ('CI-SE-EDA', 'EG', 'CI Egypt', 'CI Drug Authority', '{en}');
insert into regulator_page (regulator_id, kind, sort, label, url)
  values ('CI-SE-EDA', 'safety', 1, 'CI safety alerts', 'https://eda.example.test/alerts');
insert into regulator_page (regulator_id, kind, sort, label, url)
  values ('CI-SE-CAT', 'dhpc', 1, 'CI DHPC', 'https://sfda.example.test/dhpc');
update regulator_page set label = 'CI safety communications', url = 'https://eda.example.test/communications'
 where regulator_id = 'CI-SE-EDA';
delete from regulator_page where regulator_id = 'CI-SE-CAT';
reset role;

select pg_temp.se_assert((select label || ' ' || url from regulator_page where regulator_id = 'CI-SE-EDA')
                          = 'CI safety communications https://eda.example.test/communications',
  'an admin adds a local reference with a link, and changes the link');
select pg_temp.se_assert(not exists (select 1 from regulator_page where regulator_id = 'CI-SE-CAT'),
  'an admin removes a link');
select pg_temp.se_assert((select read_by = '{}' and not partial from regulator_page where regulator_id = 'CI-SE-EDA'),
  'a link she adds is one she opens herself');

-- ───────────── every one of those changes is in the audit log, with who made it ─────────────
select pg_temp.se_assert(exists (select 1 from audit_log where table_name = 'regulator' and row_pk = 'CI-SE-EDA'
                                    and action = 'INSERT'
                                    and actor = '00000000-0000-0000-0000-0000000000a1'),
  'adding an authority is in the audit log, with the admin who added it');
select pg_temp.se_assert(exists (select 1 from audit_log where table_name = 'regulator_page' and action = 'UPDATE'
                                    and old_row ->> 'label' = 'CI safety alerts'
                                    and new_row ->> 'label' = 'CI safety communications'),
  'changing a link keeps its old and new name and address');
select pg_temp.se_assert(exists (select 1 from audit_log where table_name = 'regulator_page' and action = 'DELETE'
                                    and old_row ->> 'label' = 'CI DHPC'
                                    and actor = '00000000-0000-0000-0000-0000000000a1'),
  'a removed link stays in the audit log');

-- ───────────── the collector's run does not fill the log ─────────────
select count(*) as se_before from audit_log where table_name = 'regulator' and row_pk = 'CI-SE-CAT' \gset
insert into regulator (id, country_code, country_name, name, languages, homepage)
  values ('CI-SE-CAT', 'SA', 'CI Saudi Arabia', 'CI Food and Drug Authority', '{ar,en}', 'https://sfda.example.test/')
  on conflict (id) do update set country_code = excluded.country_code, country_name = excluded.country_name,
    name = excluded.name, languages = excluded.languages, homepage = excluded.homepage;
select pg_temp.se_assert((select count(*) from audit_log where table_name = 'regulator' and row_pk = 'CI-SE-CAT')
                          = :se_before,
  'a catalogue run that changes nothing writes nothing to the audit log');
update regulator set homepage = 'https://www.sfda.example.test/' where id = 'CI-SE-CAT';
select pg_temp.se_assert((select count(*) from audit_log where table_name = 'regulator' and row_pk = 'CI-SE-CAT'
                                                    and action = 'UPDATE') = 1,
  'a real change to an authority is in the audit log');

-- ───────────── a reader changes nothing ─────────────
select set_config('request.jwt.claims', '{"sub":"00000000-0000-0000-0000-0000000000b2","role":"authenticated"}', false);
set role authenticated;
do $$ declare refused boolean := false; begin
  begin
    insert into regulator (id, country_code, country_name, name, languages)
      values ('CI-SE-READER', 'JO', 'CI Jordan', 'CI reader''s authority', '{en}');
  exception when insufficient_privilege then refused := true; end;
  if not refused then raise exception 'FAIL: a reader added an authority'; end if;
end $$;
update regulator_page set url = 'https://reader.example.test/' where regulator_id = 'CI-SE-EDA';
delete from regulator_page where regulator_id = 'CI-SE-EDA';
reset role;
select pg_temp.se_assert((select url from regulator_page where regulator_id = 'CI-SE-EDA')
                          = 'https://eda.example.test/communications',
  'a reader neither changes nor removes a link');

-- ───────────── clean up ─────────────
delete from regulator_page where regulator_id like 'CI-SE-%';
delete from regulator where id like 'CI-SE-%';
