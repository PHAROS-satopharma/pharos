-- PHAROS — Sources becomes the horizontal pass (2026-11-06, Dr Sama's review, points 7 and 8).
--
-- regulator_page: the pages Dr Sama checks by hand for each of her 25 reference authorities, with the exact
-- addresses of her list "Reference regulatory authority screening 2024". read_by names the PHAROS sources
-- that read each page; an empty list means the app does not read the page and she opens it herself.
-- partial marks a page the app reads only in part (the note says which part).
-- source.page_url: the page a person opens for a source (sources.yaml `page:`), never a feed or an API.
-- country_look: every "Mark as looked at", kept and never changed (the weekly report shows who looked when).
-- new_items(p_from, p_to): what the authorities published in a window, each with a link a person can open.
--
-- The enum values added here are first used in 0033: Postgres refuses a new enum value in the transaction
-- that added it.

alter type sub_kind   add value if not exists 'new_items_digest';
alter type notif_kind add value if not exists 'new_items_digest';

-- ───────────────────────────── her pages ─────────────────────────────
create type page_kind as enum ('database', 'dhpc', 'safety');

create table regulator_page (
  id            uuid primary key default gen_random_uuid(),
  regulator_id  text not null,
  kind          page_kind not null,
  sort          int not null default 0,
  label         text not null,
  url           text not null check (url ~ '^https?://'),
  read_by       text[] not null default '{}',     -- source ids; empty = not read by the app
  partial       boolean not null default false,   -- read, but only part of what the page shows
  note          text,
  unique (regulator_id, url)
);
alter table regulator_page enable row level security;
create policy regulator_page_read on regulator_page for select to authenticated using (my_role() is not null);
create policy regulator_page_admin on regulator_page for all to authenticated
  using (my_role() = 'admin') with check (my_role() = 'admin');
revoke all on regulator_page from anon;
revoke truncate on regulator_page from authenticated;
create trigger audit_regulator_page after insert or update or delete on regulator_page
  for each row execute function audit_row();

-- One line per page, in the order of her list. Addresses are hers, character for character, also where
-- the page has moved (the note says so; checked 6 Nov 2026).
insert into regulator_page (regulator_id, kind, sort, label, url, read_by, partial, note) values
  ('TGA', 'database', 1, 'Consumer Medicines Information (CMI)', 'https://www.tga.gov.au/products/australian-register-therapeutic-goods-artg/consumer-medicines-information-cmi', '{}', false, null),
  ('TGA', 'database', 2, 'Product Information (PI)', 'https://www.tga.gov.au/products/australian-register-therapeutic-goods-artg/product-information', '{}', false, null),
  ('TGA', 'safety', 3, 'Safety alerts, safety updates and recalls', 'https://www.tga.gov.au/safety', '{tga-email}', false, 'By e-mail subscription: TGA''s safety information e-mails.'),
  ('TGA', 'safety', 4, 'Safety updates', 'https://www.tga.gov.au/news/safety-updates', '{tga-email}', false, 'By e-mail subscription: TGA''s safety information e-mails.'),
  ('BASG', 'database', 1, 'Medicinal products register', 'https://aspregister.basg.gv.at/aspregister/faces/aspregister.jspx', '{}', false, null),
  ('BASG', 'dhpc', 2, 'Safety information (DHPC)', 'https://www.basg.gv.at/gesundheitsberufe/sicherheitsinformationen-dhpc', '{basg-dhpc}', false, null),
  ('FAMHP', 'safety', 1, 'News', 'https://www.famhp.be/en/news', '{famhp-email}', true, 'By e-mail subscription: the VIG-news and Flash VIG-news bulletins, not every news item.'),
  ('FAMHP', 'database', 2, 'Medicines database', 'https://medicinesdatabase.be/human-use', '{}', false, null),
  ('HC', 'database', 1, 'Drug Product Database', 'https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/drug-product-database.html', '{}', false, null),
  ('HC', 'safety', 2, 'Health Product InfoWatch', 'https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/health-product-infowatch.html', '{}', false, null),
  ('DKMA', 'dhpc', 1, 'Direct safety information sent (DHPC)', 'https://laegemiddelstyrelsen.dk/da/bivirkninger/direkte-sikkerhedsinformation/udsendte-meddelelser/', '{dkma-dhpc}', false, null),
  ('EMA', 'database', 1, 'Medicines (EPAR)', 'https://www.ema.europa.eu/en/medicines', '{spc-ema-epar}', false, 'Label watch, for our ingredients only.'),
  ('EMA', 'dhpc', 2, 'Direct healthcare professional communications', 'https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/pharmacovigilance-post-authorisation/direct-healthcare-professional-communications', '{ema-dhpc}', false, null),
  ('EMA', 'safety', 3, 'Home page news', 'https://www.ema.europa.eu/en/homepage', '{}', false, 'The app reads PRAC''s safety signal recommendations, PRAC meeting highlights and PSUSA outcomes; the other news on this page it does not.'),
  ('FIMEA', 'database', 1, 'Fimeaweb medicines search', 'https://fimea.fi/en/databases_and_registers/fimeaweb', '{}', false, null),
  ('FIMEA', 'dhpc', 2, 'Bulletins from marketing authorisation holders (DHPC)', 'https://fimea.fi/ajankohtaista/laaketurvatiedotteet/myyntiluvanhaltijoiden_tiedotteet', '{fimea-email}', false, 'By e-mail subscription: Fimea''s newsletter.'),
  ('FIMEA', 'safety', 3, 'Medicine safety bulletins', 'https://fimea.fi/ajankohtaista/laaketurvallisuustiedotteet', '{fimea-email}', false, 'By e-mail subscription: Fimea''s newsletter.'),
  ('ANSM', 'database', 1, 'Public medicines database (BDPM)', 'https://base-donnees-publique.medicaments.gouv.fr/', '{spc-bdpm}', false, 'Label watch, for our ingredients only.'),
  ('ANSM', 'safety', 2, 'Home page', 'https://ansm.sante.fr/', '{ansm-securite}', true, 'The app reads ANSM''s safety information list for medicines; the other news on this page it does not.'),
  ('BFARM', 'database', 1, 'PharmNet.Bund drug information system', 'https://www.pharmnet-bund.de/PharmNet/EN/Public/Drug-information-system/_node.html', '{}', false, null),
  ('BFARM', 'dhpc', 2, 'Rote-Hand-Briefe and information letters', 'https://www.bfarm.de/EN/Medicinal-products/Pharmacovigilance/Risk-information/Rote-Hand-Briefe-and-Information-Letters/_node.html', '{bfarm-rhb}', false, 'Read from the German page, which carries the same letters.'),
  ('BFARM', 'safety', 3, 'Risk information search', 'https://www.bfarm.de/EN/Medicinal-products/Pharmacovigilance/Risk-information/SucheRisikoinfos/_node.html', '{bfarm-risk}', false, 'Read from the German list of risk assessment procedures.'),
  ('IMA', 'database', 1, 'Medicines register', 'https://www.serlyfjaskra.is/', '{}', false, null),
  ('IMA', 'dhpc', 2, 'Letters to healthcare professionals (DHPC)', 'https://www.lyfjastofnun.is/lyf/lyfjagat/bref-til-heilbrigdisstarfsmanna-dhpc/', '{ima-dhpc}', false, null),
  ('HPRA', 'database', 1, 'Medicines', 'https://www.hpra.ie/homepage/medicines', '{}', false, null),
  ('HPRA', 'dhpc', 2, 'Safety notices', 'https://www.hpra.ie/homepage/medicines/safety-notices', '{hpra-notices}', false, null),
  ('HPRA', 'safety', 3, 'Newsletters', 'https://www.hpra.ie/homepage/about-us/publications-forms/newsletters', '{}', false, 'This address no longer opens (checked 6 Nov 2026).'),
  ('AIFA', 'database', 1, 'Medicines database', 'https://medicinali.aifa.gov.it/it/', '{}', false, null),
  ('AIFA', 'safety', 2, 'Medicine safety', 'https://www.aifa.gov.it/sicurezza-dei-farmaci', '{aifa-sicurezza}', true, 'The app reads the Note Informative Importanti and AIFA''s communications on EMA decisions; the rest of this page it does not.'),
  ('PMDA', 'database', 1, 'Package insert search', 'https://www.pmda.go.jp/PmdaSearch/iyakuSearch/', '{spc-pmda}', false, 'Label watch, for our ingredients only.'),
  ('PMDA', 'safety', 2, 'Revisions of precautions', 'https://www.pmda.go.jp/english/safety/info-services/drugs/revision-of-precautions/0001.html', '{pmda-revisions}', false, 'Read from the Japanese page.'),
  ('PMDA', 'safety', 3, 'Safety information announced by MHLW', 'https://www.pmda.go.jp/english/safety/info-services/drugs/mhlw-released/0001.html', '{}', false, null),
  ('PMDA', 'safety', 4, 'PMDA Medical Safety Information', 'https://www.pmda.go.jp/english/safety/info-services/safety-information/0001.html', '{pmda-msi}', false, 'Read from the Japanese page.'),
  ('LU_DPM', 'database', 1, 'List of medicines on the market', 'https://cns.public.lu/en/legislations/textes-coordonnes/liste-med-comm.html', '{}', false, 'This address no longer opens (checked 6 Nov 2026).'),
  ('LU_DPM', 'dhpc', 2, 'DHPC letters', 'https://sante.public.lu/fr/espace-professionnel/domaines/pharmacies-et-medicaments/pharmacovigilance/gestion-riques/dhcp.html', '{lu-dhpc}', false, null),
  ('CBG', 'database', 1, 'Medicines information bank (English)', 'https://www.geneesmiddeleninformatiebank.nl/ords/f?p=111:1:0::NO:1:P0_DOMAIN,P0_LANG:H,EN', '{}', false, null),
  ('CBG', 'database', 2, 'Medicines information bank (Dutch)', 'https://www.geneesmiddeleninformatiebank.nl/ords/f?p=111:1:0::NO:1:P0_DOMAIN,P0_LANG:H,NL', '{}', false, null),
  ('CBG', 'dhpc', 3, 'News on the safety of medicines', 'https://www.cbg-meb.nl/onderwerpen/medicijninformatie-nieuws-over-veiligheid-van-medicijnen', '{cbg-news,cbg-dhpc}', false, 'This address now opens CBG''s page on veterinary medicines (checked 6 Nov 2026); the app reads CBG''s news list and every DHPC letter page instead.'),
  ('MEDSAFE', 'database', 1, 'Data sheets and consumer information', 'https://www.medsafe.govt.nz/Medicines/infoSearch.asp', '{}', false, null),
  ('MEDSAFE', 'database', 2, 'Product and application search', 'https://www.medsafe.govt.nz/regulatory/dbsearch.asp', '{}', false, null),
  ('MEDSAFE', 'dhpc', 3, 'Dear Healthcare Professional letters', 'https://www.medsafe.govt.nz/safety/DHCPLetters.asp', '{medsafe-dhcp}', false, null),
  ('MEDSAFE', 'safety', 4, 'Prescriber Update', 'https://www.medsafe.govt.nz/publications/prescriber-update.asp', '{}', false, null),
  ('MEDSAFE', 'safety', 5, 'Safety communications', 'https://www.medsafe.govt.nz/safety/SafetyCommunications.asp', '{medsafe-comms}', false, null),
  ('DMP', 'database', 1, 'Medicines search', 'https://www.legemiddelsok.no/', '{}', false, null),
  ('DMP', 'dhpc', 2, 'Dear healthcare professional letters', 'https://www.dmp.no/bivirkninger-og-sikkerhet/tiltak-for-a-forebygge-bivirkninger/sikkerhetsinformasjon-til-helsepersonell-og-pasient/kjere-helsepersonell-brev', '{noma-dhpc}', false, null),
  ('INFARMED', 'database', 1, 'Home page (medicines database)', 'https://www.infarmed.pt/', '{}', false, null),
  ('INFARMED', 'dhpc', 2, 'Circulars', 'https://www.infarmed.pt/web/infarmed/circulares?p_p_id=paginasagregadoras_WAR_paginasagregadorasportlet&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view&p_p_col_id=column-1&p_p_col_pos=1&p_p_col_count=2&_paginasagregadoras_WAR_paginasagregadorasportlet_javax.portlet.action=advanceSearch&_paginasagregadoras_WAR_paginasagregadorasportlet_selectedOrderBy=default', '{}', false, 'The app reads Infarmed''s Alerts list instead.'),
  ('HSA', 'database', 1, 'Registered products search', 'https://eservice.hsa.gov.sg/prism/common/enquirepublic/SearchDRBProduct.do?action=load', '{}', false, null),
  ('HSA', 'dhpc', 2, 'Announcements', 'https://www.hsa.gov.sg/announcements', '{hsa-announcements}', true, 'The app reads Dear Healthcare Professional letters, product recalls, safety alerts and adverse drug reaction bulletins; other announcements it does not.'),
  ('MFDS', 'database', 1, 'Drug information (health.kr)', 'https://www.health.kr/', '{}', false, null),
  ('MFDS', 'safety', 2, 'Safety letters (health.kr)', 'https://www.health.kr/notice/safety.asp', '{}', false, 'The app reads MFDS''s own safety letters board (nedrug.mfds.go.kr); this page it does not.'),
  ('AEMPS', 'database', 1, 'CIMA medicines information', 'https://cima.aemps.es/cima/publico/home.html', '{spc-cima}', false, 'Label watch, for our ingredients only.'),
  ('AEMPS', 'dhpc', 2, 'Safety letters to healthcare professionals', 'https://www.aemps.gob.es/medicamentos-de-uso-humano/farmacovigilancia-de-medicamentos-de-uso-humano/cartas_segprofsani/?lang=en', '{aemps-dhpc}', false, null),
  ('AEMPS', 'safety', 3, 'Safety communications', 'https://www.aemps.gob.es/medicamentos-de-uso-humano/farmacovigilancia-de-medicamentos-de-uso-humano/?lang=en#comunicaSegPrevRiesgo', '{aemps-feed}', false, null),
  ('MPA', 'database', 1, 'Medicine facts search', 'https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=1', '{}', false, null),
  ('MPA', 'dhpc', 2, 'News, two categories', 'https://www.lakemedelsverket.se/sv/nyheter?c=225&c=76&p=2', '{mpa-news}', false, null),
  ('MPA', 'safety', 3, 'All news', 'https://www.lakemedelsverket.se/sv/nyheter?p=2', '{mpa-news}', true, 'The app reads four news categories and every safety news item; other news it does not.'),
  ('SWISSMEDIC', 'database', 1, 'Medicines information (AIPS)', 'https://www.swissmedicinfo.ch/?Lang=EN', '{}', false, null),
  ('SWISSMEDIC', 'dhpc', 2, 'Health Professional Communication (HPC)', 'https://www.swissmedic.ch/swissmedic/en/home/humanarzneimittel/market-surveillance/health-professional-communication--hpc-.html', '{swissmedic-hpc}', false, 'Read from the German, French and Italian pages.'),
  ('SWISSMEDIC', 'safety', 3, 'Updates', 'https://www.swissmedic.ch/swissmedic/en/home/news/updates.html', '{}', false, null),
  ('MHRA', 'database', 1, 'Products (SmPCs and leaflets)', 'https://products.mhra.gov.uk/', '{spc-mhra}', false, 'Label watch, for our ingredients only.'),
  ('MHRA', 'dhpc', 2, 'Drug Safety Update', 'https://www.gov.uk/government/publications/drug-safety-update-monthly-newsletter', '{mhra-dsu}', false, null),
  ('MHRA', 'safety', 3, 'Drug and device alerts', 'https://www.gov.uk/drug-device-alerts', '{mhra-alerts}', false, null),
  ('FDA', 'database', 1, 'Drugs@FDA', 'https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm', '{spc-dailymed}', false, 'Label watch through DailyMed, for our ingredients only.'),
  ('FDA', 'safety', 2, 'Press announcements (bottom of the FDA home page)', 'https://www.fda.gov/', '{}', false, 'The app reads FDA''s MedWatch safety alerts by e-mail and FDA''s recall records, not press announcements.')
on conflict (regulator_id, url) do nothing;

-- After the seed: a fresh database (CI) has no regulators until the first catalogue sync, so the rows above
-- are not checked against it; every row written from now on is.
alter table regulator_page add constraint regulator_page_regulator_fk
  foreign key (regulator_id) references regulator(id) on delete cascade not valid;

-- ───────────────────────────── the page a person opens for a source ─────────────────────────────
alter table source add column page_url text check (page_url is null or page_url ~ '^https?://');

-- new_items reads documents by the time PHAROS first saw them.
create index if not exists document_first_seen_at_idx on document (first_seen_at desc);

-- ───────────────────────────── "Mark as looked at" ─────────────────────────────
create table country_look (
  id            bigserial primary key,
  person_id     uuid not null references person(id),
  regulator_id  text not null references regulator(id) on delete cascade,
  looked_at     timestamptz not null default now()
);
create index country_look_person on country_look (person_id, regulator_id, looked_at desc);
alter table country_look enable row level security;
create policy country_look_read on country_look for select to authenticated using (my_role() is not null);
revoke all on country_look from anon;
revoke insert, update, delete, truncate on country_look from authenticated;

-- The signed-in person's last look at each authority.
create view v_my_country_look with (security_invoker = true) as
select regulator_id, max(looked_at) as looked_at
  from country_look
 where person_id = my_person_id()
 group by regulator_id;
revoke all on v_my_country_look from anon;

-- One look stamps every authority of the country (Germany: BfArM and the Paul-Ehrlich-Institut), as the
-- signed-in person, at the database's time.
create function mark_country_looked(p_regulator text) returns timestamptz
language plpgsql security definer set search_path = public as $$
declare
  v_person  uuid := my_person_id();
  v_country text;
  v_at      timestamptz := now();
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
revoke all on function mark_country_looked(text) from public, anon;
grant execute on function mark_country_looked(text) to authenticated;

-- ───────────────────────────── what the authorities published ─────────────────────────────
-- Every document PHAROS first saw in [p_from, p_to), except history (backfill) and the label watch and
-- literature, which have screens of their own. link is a page a person can open: FDA's Enforcement Report
-- for an openFDA recall (rows stored before 0032 carry the API query), the source's page for anything that
-- looks like a feed, and null for an e-mail with no web page (email_id and email_r2_key open it instead).
-- Security invoker: row-level security decides who sees what (someone not on the team sees nothing).
create function new_items(p_from timestamptz, p_to timestamptz default now())
returns table (
  document_id     uuid,
  source_id       text,
  regulator_id    text,
  regulator_name  text,
  country_name    text,
  country_code    text,
  source_kind     source_kind,
  title_orig      text,
  lang            text,
  link            text,
  published_date  date,
  first_seen_at   timestamptz,
  doc_type        doc_type,
  matched         boolean,
  r2_key          text,
  mime            text,
  email_id        uuid,
  email_r2_key    text
)
language sql stable security invoker set search_path = public as $$
  select d.id, d.source_id, r.id, r.name, r.country_name, r.country_code, s.kind, d.title_orig, d.lang,
         case
           when d.url like 'email:%' then null
           when d.url ~* '^https?://api\.fda\.gov/' then
             'https://www.accessdata.fda.gov/scripts/ires/index.cfm'
               || coalesce('?Event=' || nullif(btrim(d.structured ->> 'event_id'), ''), '')
           when d.url ~* '(\.(xml|json|rss|atom)([?#]|$)|/(rss|feed|atom)(/|[?#]|$)|^https?://api\.)' then
             coalesce(s.page_url, r.homepage)
           else d.url
         end,
         d.published_date, d.first_seen_at, d.doc_type,
         exists (select 1 from match m where m.document_id = d.id),
         d.r2_key, d.mime,
         case when d.structured ->> 'inbound_email_id' ~* '^[0-9a-f-]{36}$'
              then (d.structured ->> 'inbound_email_id')::uuid end,
         d.structured ->> 'raw_r2_key'
    from document d
    join source s on s.id = d.source_id
    join regulator r on r.id = s.regulator_id
   where d.first_seen_at >= p_from
     and d.first_seen_at < coalesce(p_to, now())
     and not d.is_backfill
     and s.kind not in ('spc', 'literature')
$$;
revoke all on function new_items(timestamptz, timestamptz) from public, anon;
grant execute on function new_items(timestamptz, timestamptz) to authenticated;
