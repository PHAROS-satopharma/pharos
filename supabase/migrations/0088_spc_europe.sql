-- PHAROS — the label watch reads eight European databases, and every database page it cannot read says why
-- (2026-11-07).
--
-- Each of the eight has its own label-watch source (collectors/sources.yaml; collectors/spc/cbg.py, famhp.py,
-- aifa.py, mpa.py, infomed.py, hpra.py, basg.py, lyfja.py), each read from GitHub on 6 Nov 2026
-- (probe-databases.yml). Centrally authorised medicines stay with EMA's EPARs (spc-ema-epar) in every country.
-- HPRA and BASG are read with the key each site's own page hands every visitor, fetched fresh each run and never
-- stored (his decision, 6 Nov 2026).

update regulator_page p
   set read_by = '{spc-cbg}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only, from the CBG''s weekly list of every SmPC (metadata.csv).'
 where p.regulator_id = 'CBG' and p.kind = 'database'
   and p.url in ('https://www.geneesmiddeleninformatiebank.nl/ords/f?p=111:1:0::NO:1:P0_DOMAIN,P0_LANG:H,EN',
                 'https://www.geneesmiddeleninformatiebank.nl/ords/f?p=111:1:0::NO:1:P0_DOMAIN,P0_LANG:H,NL');

update regulator_page p
   set read_by = '{spc-famhp}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only, from the FAMHP''s list of every SmPC document.'
 where p.regulator_id = 'FAMHP' and p.kind = 'database' and p.url = 'https://medicinesdatabase.be/human-use';

update regulator_page p
   set read_by = '{spc-aifa}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only: the RCP of each nationally authorised medicine.'
 where p.regulator_id = 'AIFA' and p.kind = 'database' and p.url = 'https://medicinali.aifa.gov.it/it/';

update regulator_page p
   set read_by = '{spc-mpa}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only: the SmPC of each approved, nationally authorised product.'
 where p.regulator_id = 'MPA' and p.kind = 'database'
   and p.url = 'https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta?activeTab=1';

update regulator_page p
   set read_by = '{spc-infomed}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only, through Infomed: the RCM of each authorised and marketed '
           || 'medicine.'
 where p.regulator_id = 'INFARMED' and p.kind = 'database' and p.url = 'https://www.infarmed.pt/';

update regulator_page p
   set read_by = '{spc-hpra}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only: the SPC of each nationally authorised medicine, through the '
           || 'search on HPRA''s own page.'
 where p.regulator_id = 'HPRA' and p.kind = 'database' and p.url = 'https://www.hpra.ie/homepage/medicines';

update regulator_page p
   set read_by = '{spc-basg}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only, through BASG''s Medikamente Info Austria: the '
           || 'Fachinformation of each nationally authorised medicine.'
 where p.regulator_id = 'BASG' and p.kind = 'database'
   and p.url = 'https://aspregister.basg.gv.at/aspregister/faces/aspregister.jspx';

update regulator_page p
   set read_by = '{spc-lyfja}'::text[],
       partial = false,
       note = 'Label watch, for our ingredients only: the SmPC of each nationally authorised medicine in the '
           || 'ingredient''s ATC group (a combination filed under another group is not found).'
 where p.regulator_id = 'IMA' and p.kind = 'database' and p.url = 'https://www.serlyfjaskra.is/';

-- The pages that cannot be read without getting past a block, each with its reason. Nothing is worked around.
update regulator_page p
   set note = 'Not read: the TGA''s search times out from the app''s servers and opens behind a licence page.'
 where p.regulator_id = 'TGA' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: Fimea''s site answers the app with a bot check (HTTP 403). Centrally authorised '
           || 'medicines are read through EMA.'
 where p.regulator_id = 'FIMEA' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: the medicines search refuses the app at its gateway (HTTP 403). Centrally authorised '
           || 'medicines are read through EMA.'
 where p.regulator_id = 'DMP' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: PharmNet.Bund''s drug information opens only after a sign-in that needs JavaScript. '
           || 'Centrally authorised medicines are read through EMA.'
 where p.regulator_id = 'BFARM' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: AIPS opens only after its terms of use are accepted, which the app does not do on '
           || 'anyone''s behalf.'
 where p.regulator_id = 'SWISSMEDIC' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: the search is behind a bot check.'
 where p.regulator_id = 'HSA' and p.kind = 'database';

update regulator_page p
   set note = 'Not read: this address no longer opens (checked 6 Nov 2026), and the list it held is a price list '
           || 'without labels. Centrally authorised medicines are read through EMA.'
 where p.regulator_id = 'LU_DPM' and p.kind = 'database';
