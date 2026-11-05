# sfda-sa (PHAROS fixture)

Saudi Food and Drug Authority, Arabic. Saved 4 November 2026:

* `warnings.html` — https://www.sfda.gov.sa/ar/warnings : cards `div.node--type-warning`
  (`p.head-subtitle` title, date YYYY-MM-DD, tag غذاء/دواء, link `/ar/warnings/<id>`).
* `warnings_drug.html` — the same list filtered to drugs (`field_type_target_id=5`), one 2010 item.
* `drugs_circulars_withdrawal.html` — https://www.sfda.gov.sa/ar/drugs_circulars_withdrawal :
  recall table (product, type, action, level, `time[datetime]`, link).
* `drugs_circulars_withdrawal_last.html` — the same table's last page (`?page=16`, saved 5 November
  2026): one 2023 row and no "next" link. The table is in no date order, so every page is read.
No SFDA DHPC page was found. Parser: `generic_html`, preset `sfda-sa`.
