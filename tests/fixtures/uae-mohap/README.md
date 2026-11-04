# uae-mohap (PHAROS fixture)

Source tried: https://mohap.gov.ae/ar/media-center/drug-alerts (UAE Ministry of Health and
Prevention; Arabic/English).

Unreachable on 4 November 2026: the connection was reset (curl error 35) before any byte was received. No page
saved, so `generic_html` has no preset for this source; its `item_selector`/`link_pattern` must be
set in sources.yaml once the page has been seen (the source should stay disabled until then).
