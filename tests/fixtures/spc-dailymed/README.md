# spc-dailymed (PHAROS fixture)

DailyMed web services v2, saved 5 November 2026:

* `spls_meloxicam_rx_p1.json`, `spls_meloxicam_rx_p2.json` —
  `/dailymed/services/v2/spls.json?drug_name=meloxicam&doctype=34391-3&pagesize=100&page=1|2`:
  186 human prescription labels on 2 pages. The same search without `doctype` gives 209, including
  veterinary labels (METACAM, Boehringer Ingelheim Animal Health).
* `spl_445d7cbf.xml` — `/dailymed/services/v2/spls/445d7cbf-bd3e-a54f-e063-6294a90a67a5.xml`,
  MELOXICAM TABLET [ADVANCED RX OF TENNESSEE, LLC], HL7 SPL, effectiveTime 20261102.
