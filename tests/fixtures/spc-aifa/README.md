# spc-aifa (PHAROS fixture)

AIFA Banca Dati Farmaci, saved 7 November 2026.

* `ricerca_ivabradina_0.json`: `https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=ivabradina&page=0`,
  the first page of the search (its later pages are not saved: the test reads the list as partial).
* `rcp_44509.pdf`: the RCP of AIC 044509 (Ivabradina Anpharm), from
  `…/organizzazione/<codiceSis>/farmaci/044509/stampati?ts=RCP`, with AIFA's page footer ("Documento reso
  disponibile da AIFA il 30/05/2020") and margin stamp.
* `rcp_040040.pdf` (Epifloxin, Epifarma), `rcp_042889.pdf` (Paracetamolo Mylan Italia) and `rcp_050875.pdf`
  (Distem, Bruno Farmaceutici): their RCPs from `…/farmaci/<AIC>/stampati?ts=RCP`, saved 17 November 2026. The
  label watch on GitHub (poppler's pdftotext) found no section 4.4 in them that morning; xpdf's reads them.
