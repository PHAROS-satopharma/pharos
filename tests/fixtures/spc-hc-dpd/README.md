# spc-hc-dpd (PHAROS fixture)

Health Canada Drug Product Database, saved 6 November 2026, 23:51–23:56 Cairo.

* `activeingredient_ivabradine.json`: `/api/drug/activeingredient/?lang=en&type=json&ingredientname=ivabradine`,
  drug codes 94728 (5 mg) and 94729 (7.5 mg).
* `marketed_excerpt.json`: six rows of `/api/drug/drugproduct/?lang=en&type=json&status=2` (13,385 rows,
  3.4 MB): the two LANCORA rows, one veterinary row and the first three rows, unchanged. Cut to six rows here
  only to keep the fixture small.
* `info_94728.html`: `/dpd-bdpp/info?lang=eng&code=94728`, linking the monograph
  `https://pdf.hres.ca/dpd_pm/00080705.PDF`, "Date: 2025-05-30".
* `pm_00080705.pdf`: that monograph (LANCORA, Servier Canada, 41 pages, the 2020 template; Last-Modified
  26 Jun 2025, the product's `last_update_date`).
