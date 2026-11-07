# spc-aifa (PHAROS fixture)

AIFA Banca Dati Farmaci, saved 7 November 2026.

* `ricerca_ivabradina_0.json`: `https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=ivabradina&page=0`,
  the first page of the search (its later pages are not saved: the test reads the list as partial).
* `rcp_44509.pdf`: the RCP of AIC 044509 (Ivabradina Anpharm), from
  `…/organizzazione/<codiceSis>/farmaci/044509/stampati?ts=RCP`, with AIFA's page footer ("Documento reso
  disponibile da AIFA il 30/05/2020") and margin stamp.
