-- PHAROS — FDA is read again, from FDA's own e-mail lists published as feeds (2026-11-06).
--
-- fda.gov refuses the servers PHAROS runs on, so Dr Sama's FDA press page was not read (0038). FDA sends its
-- e-mail lists through GovDelivery, and GovDelivery publishes each list as a public RSS feed on its own host,
-- which answers our servers. Four new catalogue sources read them (collectors/sources.yaml):
--   fda-press-gd      FDA Press Releases                       (her page: press announcements)
--   fda-druginfo-gd   Drug Information, which carries the Drug Safety Communications
--   fda-medwatch-gd   MedWatch Safety Alerts
--   fda-srlc-gd       Drug Safety-related Labeling Changes
-- The sources' rows are made by the collector's next catalogue sync; until then the Sources screen shows the
-- page as not read, since it counts only sources that exist and are on.
-- Matched on (regulator, her address): a page an admin has since moved is left as it is.

update regulator_page p
   set read_by = '{fda-press-gd,fda-druginfo-gd,fda-medwatch-gd}'::text[],
       partial = false,
       note = 'Read from FDA''s own e-mail lists, which GovDelivery publishes as feeds: Press Releases, Drug '
           || 'Information (it carries the Drug Safety Communications) and MedWatch Safety Alerts. fda.gov itself '
           || 'refuses our servers. Each feed holds its last 25 bulletins, so nothing older than that was read.'
 where p.regulator_id = 'FDA' and p.url = 'https://www.fda.gov/';
