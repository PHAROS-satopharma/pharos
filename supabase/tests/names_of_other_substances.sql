-- PHAROS CI — names that belong to another substance are removed with what they found (0073).
-- Runs on the database ci.yml prepared: the cases are made, then the migration runs again on them.

create function pg_temp.ns_assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAIL: %', msg; end if;
  raise notice 'ok: %', msg;
end $$;

insert into ingredient (id, inn_en) values
  ('00000000-0000-0000-0000-00000073a001', 'levofloxacin'),
  ('00000000-0000-0000-0000-00000073a002', 'ivabradine');
insert into ingredient_term (id, ingredient_id, lang, term, kind, mode, source) values
  ('00000000-0000-0000-0000-00000073c001', '00000000-0000-0000-0000-00000073a001', 'en', 'levofloxacin', 'inn', 'stem', 'wikidata'),
  ('00000000-0000-0000-0000-00000073c002', '00000000-0000-0000-0000-00000073a001', 'en', 'Ofloxacin', 'synonym', 'stem', 'wikidata'),
  ('00000000-0000-0000-0000-00000073c003', '00000000-0000-0000-0000-00000073a001', 'en', 'Floxin', 'synonym', 'stem', 'wikidata'),
  ('00000000-0000-0000-0000-00000073c004', '00000000-0000-0000-0000-00000073a002', 'ja', '2190039', 'code', 'exact', 'pmda');
insert into regulator (id, country_code, country_name, name, languages, homepage) values
  ('CI-NS', 'XS', 'CI Substanceland', 'CI Agency', '{en}', null);
insert into source (id, regulator_id, kind, channel, url, parser, languages, page_url, enabled) values
  ('ci-ns-html', 'CI-NS', 'safety', 'html', 'https://ns.example.test/', 'generic_html', '{en}',
   'https://ns.example.test/', true);

-- b001: the ofloxacin PSUSA, found only by "Ofloxacin"          -> its issue goes, the notice stays
-- b002: a fluoroquinolone letter naming both                     -> keeps levofloxacin (its INN matched too)
-- b003: the CHMP newsletter, found only by a near-spelt code     -> its issue goes
-- b004: an ofloxacin notice someone has already reviewed          -> kept exactly as it is
insert into document (id, source_id, external_id, url, title_orig, lang, doc_type, published_date, first_seen_at,
                      is_backfill) values
  ('00000000-0000-0000-0000-00000073b001', 'ci-ns-html', 'ns1', 'https://ns.example.test/1',
   'ofloxacin (systemic use): PSUSA', 'en', 'psusa', '2025-11-28', '2026-11-06 00:39+00', true),
  ('00000000-0000-0000-0000-00000073b002', 'ci-ns-html', 'ns2', 'https://ns.example.test/2',
   'Fluoroquinolones: ofloxacin and levofloxacin', 'en', 'dhpc', '2023-07-01', '2026-11-06 00:39+00', true),
  ('00000000-0000-0000-0000-00000073b003', 'ci-ns-html', 'ns3', 'https://ns.example.test/3',
   'CHMP Meeting Highlights Juli 2026', 'en', 'newsletter', '2026-10-06', '2026-11-06 11:20+00', true),
  ('00000000-0000-0000-0000-00000073b004', 'ci-ns-html', 'ns4', 'https://ns.example.test/4',
   'Ofloxacin: tendon rupture', 'en', 'dhpc', '2024-01-01', '2026-11-06 00:39+00', true);
insert into issue (id, doc_type, title, anchor_document_id, first_date, is_backfill, class_only) values
  ('00000000-0000-0000-0000-00000073e001', 'psusa', 'ofloxacin (systemic use): PSUSA',
   '00000000-0000-0000-0000-00000073b001', '2025-11-28', true, false),
  ('00000000-0000-0000-0000-00000073e002', 'dhpc', 'Fluoroquinolones: ofloxacin and levofloxacin',
   '00000000-0000-0000-0000-00000073b002', '2023-07-01', true, false),
  ('00000000-0000-0000-0000-00000073e003', 'newsletter', 'CHMP Meeting Highlights Juli 2026',
   '00000000-0000-0000-0000-00000073b003', '2026-10-06', true, false),
  ('00000000-0000-0000-0000-00000073e004', 'dhpc', 'Ofloxacin: tendon rupture',
   '00000000-0000-0000-0000-00000073b004', '2024-01-01', true, false);
insert into issue_document (issue_id, document_id, link, method)
select ('00000000-0000-0000-0000-00000073e00' || n)::uuid, ('00000000-0000-0000-0000-00000073b00' || n)::uuid,
       'anchor', 'auto'
  from generate_series(1, 4) n;
insert into issue_ingredient values
  ('00000000-0000-0000-0000-00000073e001', '00000000-0000-0000-0000-00000073a001'),
  ('00000000-0000-0000-0000-00000073e002', '00000000-0000-0000-0000-00000073a001'),
  ('00000000-0000-0000-0000-00000073e003', '00000000-0000-0000-0000-00000073a002'),
  ('00000000-0000-0000-0000-00000073e004', '00000000-0000-0000-0000-00000073a001');
insert into match (document_id, ingredient_id, term_id, field, matched_text, confidence) values
  ('00000000-0000-0000-0000-00000073b001', '00000000-0000-0000-0000-00000073a001',
   '00000000-0000-0000-0000-00000073c002', 'title', 'ofloxacin', 'high'),
  ('00000000-0000-0000-0000-00000073b002', '00000000-0000-0000-0000-00000073a001',
   '00000000-0000-0000-0000-00000073c002', 'title', 'ofloxacin', 'high'),
  ('00000000-0000-0000-0000-00000073b002', '00000000-0000-0000-0000-00000073a001',
   '00000000-0000-0000-0000-00000073c001', 'title', 'levofloxacin', 'high'),
  ('00000000-0000-0000-0000-00000073b003', '00000000-0000-0000-0000-00000073a002',
   '00000000-0000-0000-0000-00000073c004', 'attachment', '21900', 'possible'),
  ('00000000-0000-0000-0000-00000073b004', '00000000-0000-0000-0000-00000073a001',
   '00000000-0000-0000-0000-00000073c002', 'title', 'Ofloxacin', 'high');
update issue set status = 'not_relevant' where id = '00000000-0000-0000-0000-00000073e004';

\ir ../migrations/0073_names_of_other_substances.sql

select pg_temp.ns_assert(not exists (select 1 from ingredient_term where id in
         ('00000000-0000-0000-0000-00000073c002', '00000000-0000-0000-0000-00000073c003')),
       'Ofloxacin and Floxin are no longer names of levofloxacin');
select pg_temp.ns_assert(exists (select 1 from ingredient_term where id = '00000000-0000-0000-0000-00000073c001')
                     and exists (select 1 from ingredient_term where id = '00000000-0000-0000-0000-00000073c004'),
       'the INN and the Japan code stay');
select pg_temp.ns_assert(not exists (select 1 from issue where id in
         ('00000000-0000-0000-0000-00000073e001', '00000000-0000-0000-0000-00000073e003')),
       'the issues only a wrong name or a near-spelt code made are gone');
select pg_temp.ns_assert((select count(*) from document where id in
         ('00000000-0000-0000-0000-00000073b001', '00000000-0000-0000-0000-00000073b003')) = 2,
       'their notices stay stored');
select pg_temp.ns_assert(exists (select 1 from issue_ingredient
                                  where issue_id = '00000000-0000-0000-0000-00000073e002'
                                    and ingredient_id = '00000000-0000-0000-0000-00000073a001')
                     and (select count(*) from match where document_id = '00000000-0000-0000-0000-00000073b002') = 1,
       'a notice its own INN also found keeps the ingredient, without the wrong match');
select pg_temp.ns_assert(exists (select 1 from issue_ingredient
                                  where issue_id = '00000000-0000-0000-0000-00000073e004')
                     and (select status from issue where id = '00000000-0000-0000-0000-00000073e004') = 'not_relevant',
       'an issue someone already decided keeps its ingredient and its decision');
select pg_temp.ns_assert((select count(*) from audit_log where table_name = 'match' and action = 'DELETE'
                            and old_row->>'document_id' like '00000000-0000-0000-0000-00000073b00%') = 4
                     and (select count(*) from audit_log where table_name = 'issue' and action = 'DELETE'
                            and row_pk in ('00000000-0000-0000-0000-00000073e001',
                                           '00000000-0000-0000-0000-00000073e003')) = 2,
       'every removed match and issue is in the audit log');
