# spc-dailymed (PHAROS fixture)

DailyMed web services v2, saved 5 November 2026:

* `spls_meloxicam_rx_p1.json`, `spls_meloxicam_rx_p2.json` —
  `/dailymed/services/v2/spls.json?drug_name=meloxicam&doctype=34391-3&pagesize=100&page=1|2`:
  186 human prescription labels on 2 pages. The same search without `doctype` gives 209, including
  veterinary labels (METACAM, Boehringer Ingelheim Animal Health).
* `spl_445d7cbf.xml` — `/dailymed/services/v2/spls/445d7cbf-bd3e-a54f-e063-6294a90a67a5.xml`,
  MELOXICAM TABLET [ADVANCED RX OF TENNESSEE, LLC], HL7 SPL, effectiveTime 20261102.

Saved 6 November 2026, the over-the-counter lists FDA approves label by label
(`/spls.json?drug_name=<name>&doctype=34390-5&marketing_category_code=<code>&pagesize=100&page=1`):

* `spls_meloxicam_otc_nda.json` — meloxicam, C73594 (NDA): DailyMed's answer for an empty list
  (`total_pages` 0).
* `spls_phenylephrine_otc_nda.json` — phenylephrine, C73594 (NDA): 6 labels (Advil Sinus, Advil Allergy …).
* `spls_phenylephrine_otc_anda.json` — phenylephrine, C73584 (ANDA): 2 labels (Sudafed PE Head Congestion
  plus Pain, a Remedy Pack kit).
* `spls_phenylephrine_otc_ag.json` — phenylephrine, C73605 (NDA authorized generic): empty.
