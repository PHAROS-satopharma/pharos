-- PHAROS — the label watch reads Korea, Canada and New Zealand (2026-11-07).
--
-- Three database pages of her list were listed and never read. Each now has its own label-watch source
-- (collectors/sources.yaml; collectors/spc/nedrug.py, hc_dpd.py, medsafe.py), all three read from GitHub on
-- 6 Nov 2026 (probe-databases.yml, run 42296657165):
--   * MFDS: her page is health.kr, which needs JavaScript; the regulator's own database, nedrug.mfds.go.kr,
--     answers plain requests and keeps every past version of a label;
--   * Health Canada: the Drug Product Database API and each marketed product's monograph (pdf.hres.ca);
--   * Medsafe: its two searches answer only through a live JavaScript connection, so the data sheets are read
--     from Medsafe's plain data-sheet list, and the page is marked partial: a brand-named data sheet is found
--     only when Medsafe's updates page names its ingredient. Its product and application search stays unread.

update regulator_page p
   set read_by = '{spc-nedrug}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only, through MFDS''s own database nedrug.mfds.go.kr '
           || '(health.kr needs JavaScript).'
 where p.regulator_id = 'MFDS' and p.kind = 'database' and p.url = 'https://www.health.kr/';

update regulator_page p
   set read_by = '{spc-hc-dpd}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only: the product monograph of each marketed product.'
 where p.regulator_id = 'HC' and p.kind = 'database'
   and p.url = 'https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/drug-product-database.html';

update regulator_page p
   set read_by = '{spc-medsafe}'::text[],
       partial = true,
       note = 'Label watch, for our ingredients only, from Medsafe''s data sheet list. Medsafe''s search needs '
           || 'JavaScript, so a brand-named data sheet is found only when this year''s updates page names its '
           || 'ingredient.'
 where p.regulator_id = 'MEDSAFE' and p.kind = 'database'
   and p.url = 'https://www.medsafe.govt.nz/Medicines/infoSearch.asp';

update regulator_page p
   set note = 'Not read: this search answers only through a live JavaScript connection. The data sheets are '
           || 'read from Medsafe''s data sheet list.'
 where p.regulator_id = 'MEDSAFE' and p.kind = 'database'
   and p.url = 'https://www.medsafe.govt.nz/regulatory/dbsearch.asp';
