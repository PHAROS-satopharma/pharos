-- PHAROS — Health Canada's InfoWatch is read from its e-mails (2026-11-06).
--
-- canada.ca does not answer the servers PHAROS runs on (every request timed out, 6 Nov 2026), so her Health
-- Product InfoWatch page was the one page of hers not read (0038). Health Canada sends InfoWatch and its
-- advisories by e-mail (MedEffect e-Notice), subscribed for the PV mailbox on 6 Nov 2026 ("Outside of Canada",
-- Drugs). The new catalogue source hc-email reads them (collectors/sources.yaml); its row is made by the
-- collector's next catalogue sync, and until the first e-mail arrives the Sources screen says it is waiting.
-- Matched on (regulator, her address): a page an admin has since moved is left as it is.

update regulator_page p
   set read_by = '{hc-email}'::text[],
       partial = false,
       note = 'By e-mail subscription: Health Canada''s MedEffect e-Notice (InfoWatch and advisories). '
           || 'canada.ca itself does not answer our servers.'
 where p.regulator_id = 'HC'
   and p.url = 'https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/health-product-infowatch.html';
